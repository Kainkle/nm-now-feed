"""epg.pw XMLTV ingest, multi-country.

Source of truth for schedules: https://epg.pw/xmltv/epg_{CC}.xml.gz — one file per
country, ~21 country files exist. We carry nine: US GB DE FR AU NZ BR CA RU.

epg.pw carries title + desc only — no sub-title/episode/rating/new flags. `is_live`
is derived from the "Live: " title prefix, which the files use consistently for live
sport and talk coverage (observed in the US and CA files; RU/BR simply don't use it).

THE TIMEZONE TRAP (measured 2026-08-26, every file anchored independently):

Every file labels every stamp "+0000", and every file lies — each stamps its
programmes in some ingestion office's LOCAL wall clock. The offset is a property of
the FILE, not of the pipeline: the US file is UTC+8 wall, the GB file is UTC-8 wall
(the opposite sign!), the rest are UTC+8. Anchors, one per file:

  US  FNC Jesse Watters    really 8pm  ET = 00:00Z -> stamped 20260826080000 +0000
  GB  BBC News at One      really 1pm  UK = 12:00Z -> stamped 20260826040000 +0000
      (+9 canonical BBC One slots agree: Pointless 17:15, HUTH 11:15, Repair Shop 15:30)
  DE  Das Erste Tagesthemen really 22:15 CEST = 20:15Z -> stamped 20260826041500 +0000
  FR  France 2 Journal 20h00 really 20:00 CEST = 18:00Z -> stamped 20260826020000 +0000
  AU  Seven News At 4      really 4pm AEST = 06:00Z -> stamped 20260826140000 +0000
  NZ  1News at Six (on +1) really 7pm NZST = 07:00Z -> stamped 20260826150000 +0000
  BR  Globo Jornal Nacional really 20:30 BRT = 23:30Z -> stamped 20260826073000 +0000
  CA  Global News at 6     really 6pm  ET = 22:00Z -> stamped 20260826060000 +0000
  RU  Rossiya-1 +4 Vesti   really 8pm  +4 = 13:00Z -> stamped 20260826210000 +0000

GB being the opposite sign of its siblings is not a theory, it is nine consecutive
canonical BBC One slots. Never "normalise" these constants to match each other.

build.py's ANCHORS check re-measures one self-titled show per file on every build
and FAILS the build if any lands >45min off its true slot — so if epg.pw ever
changes a file's stamps, the build goes red instead of the guide going wrong.
"""

import gzip
import re
import urllib.request
from datetime import datetime, timedelta, timezone

EPG_URL = "https://epg.pw/xmltv/epg_%s.xml.gz"

# Countries we ingest, with the hours-to-SUBTRACT correction for each file's
# mislabelled wall-clock stamps (see the module docstring's anchor table).
EPG_COUNTRIES: dict[str, int] = {
    "US": 8, "GB": -8, "DE": 8, "FR": 8, "AU": 8, "NZ": 8, "BR": 8, "CA": 8, "RU": 8,
}

_PROG_OPEN = re.compile(r"<programme ([^>]*)>")
# Attribute order inside <programme> varies (channel-first in the wild) — never assume.
_ATTR = lambda tag, name: re.search(r'%s="([^"]*)"' % name, tag)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
_DESC = re.compile(r"<desc[^>]*>(.*?)</desc>", re.S)
_TAG = re.compile(r"<[^>]+>")


def _as_utc(stamp: str, offset: str | None, wall_hours: int) -> datetime:
    dt = datetime.strptime(stamp, "%Y%m%d%H%M%S")
    if offset:
        sign = 1 if offset[0] == "+" else -1
        dt = dt.replace(tzinfo=timezone(sign * timedelta(hours=int(offset[1:3]), minutes=int(offset[3:5]))))
    else:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc) - timedelta(hours=wall_hours)


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return _TAG.sub("", text).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">") \
        .replace("&quot;", '"').replace("&apos;", "'").strip()


def fetch(path: str, country: str) -> None:
    """Download one country's gz snapshot to `path`."""
    req = urllib.request.Request(EPG_URL % country, headers={"User-Agent": "nm-now-feed/1.0"})
    with urllib.request.urlopen(req, timeout=300) as r, open(path, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)


def _norm_key(display: str) -> str:
    """Normalise a display-name for matching: lowercase, drop quality tokens, squash.

    Splits on unicode non-word chars so Cyrillic names survive (the RU file's display
    names are Russian; ASCII-only classes would reduce every one of them to digits).
    """
    tokens = [t for t in re.split(r"[^\w]+", display.lower(), flags=re.UNICODE) if t]
    tokens = [t for t in tokens if t not in ("hd", "sd", "fhd", "uhd")]
    return "".join(tokens)


def scan(gz_path: str, want_norms: dict[str, list[str]], want_ids: dict[str, str], anchor_ids: dict[str, str], since: datetime, until: datetime, wall_hours: int):
    """One streaming pass over a country file.

    `want_norms` maps _norm_key(channel name) -> [stable keys] (feed channel numbers);
    matching.py may seed several norms for one number (synonyms, e.g. the Latin
    transliteration of a Cyrillic channel) and several numbers for one norm (dlhd
    twins of cdnlive channels) — one epg id then carries the schedule for every twin.
    `want_ids` maps a raw epg channel id -> the
    same key and binds irrevocably ahead of any name matching — the US lineup's curated
    ids go through it. All <channel> blocks precede the programmes
    in these files, so the pass resolves which epg ids are wanted as it meets them, then
    keeps only their programmes.

    Channel binding, in order: exact normalised-name match, then a prefix-variant
    fallback for wants still unmatched after the exact pass (a second sweep over the
    collected channel list, run once programmes start arriving — binding one epg id
    per want, preferring non-timeshift and shorter displays).

    Returns ({epg_id: display_name}, {feed_number: [programme dict, ...]}) — the
    programme dicts are feed-ready (guide handoff 2.2) except `id`, which build.py
    prefixes with the channel number.
    """
    matched: dict[str, list[str]] = {}  # epg channel id -> keys (feed number, anchor key, …)
    displays: dict[str, str] = {}       # epg channel id -> display name
    # every channel seen, kept for the variant sweep: (norm, display, id)
    seen: list[tuple[str, str, str]] = []
    variants_done = False
    out: dict[str, list[dict]] = {}
    open_blk = None

    def sweep_variants():
        """Prefix-bind remaining wants. Exact matches always win; this only runs once."""
        bound = {n for keys in matched.values() for n in keys}
        for wnorm, numbers in want_norms.items():
            for number in numbers:
                if number in bound:
                    continue
                cands = [
                    (dn, cid) for (norm, dn, cid) in seen
                    if cid not in matched and norm != wnorm
                    and (norm.startswith(wnorm) or wnorm.startswith(norm))
                    and min(len(norm), len(wnorm)) >= 6
                ]
                if not cands:
                    continue
                # Non-timeshift first, then the shortest display (national beats regional),
                # then lowest id — fully deterministic for a given file.
                cands.sort(key=lambda c: ("+1" in c[0].lower() or "plus 1" in c[0].lower(), len(c[0]), c[1]))
                matched[cands[0][1]] = [number]
                displays[cands[0][1]] = cands[0][0]
                # bound must grow as we bind: two norms can share a number (synonyms),
                # and without this the second prefix-binds a second epg id to it and
                # the schedule lands twice under that number.
                bound.add(number)

    def close_channel(blk: str):
        cid = re.search(r'id="([^"]+)"', blk)
        d = re.search(r"<display-name[^>]*>(.*?)</display-name>", blk, re.S)
        if not (cid and d):
            return
        display = _clean(d.group(1))
        norm = _norm_key(display)
        seen.append((norm, display, cid.group(1)))
        keys = []
        # Curated ids bind first and irrevocably — the US lineup's judgment calls
        # (ABC -> national feed, NESN -> the overflow feed) are decisions, not guesses.
        # Anchor ids (build.py's timezone check) are observers: an id can carry a row
        # key AND an anchor key, and the programmes flow under both — the row keeps
        # its schedule and the anchor check gets its own copy. An anchor must never
        # steal a channel from the lineup.
        if cid.group(1) in want_ids:
            keys.append(want_ids[cid.group(1)])
        if cid.group(1) in anchor_ids:
            keys.append(anchor_ids[cid.group(1)])
        # A norm can name several feed numbers (dlhd twins); bind every unbound one.
        # The global guard keeps each number on exactly ONE epg id, so twin rows share
        # a single epg channel's schedule instead of each inventing its own.
        for key in want_norms.get(norm, ()):
            if key not in keys and key not in {n for ks in matched.values() for n in ks}:
                keys.append(key)
        if keys:
            matched[cid.group(1)] = keys
            displays[cid.group(1)] = display

    with gzip.open(gz_path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            if open_blk is not None:
                open_blk += line
                if "</channel>" in open_blk:
                    close_channel(open_blk)
                    open_blk = None
                elif "</programme>" in open_blk:
                    m = _PROG_OPEN.search(open_blk)
                    if not m:
                        open_blk = None
                        continue
                    attrs = m.group(1)
                    chan_m = _ATTR(attrs, "channel")
                    start_m, stop_m = _ATTR(attrs, "start"), _ATTR(attrs, "stop")
                    if not (chan_m and start_m and stop_m):
                        open_blk = None
                        continue
                    chan = chan_m.group(1)
                    if chan in matched:
                        try:
                            sm = re.match(r"(\d{14})\s*([+-]\d{4})?", start_m.group(1))
                            em = re.match(r"(\d{14})\s*([+-]\d{4})?", stop_m.group(1))
                            st = _as_utc(sm.group(1), sm.group(2), wall_hours)
                            en = _as_utc(em.group(1), em.group(2), wall_hours)
                        except ValueError:
                            open_blk = None
                            continue
                        if en > since and st < until:
                            dur = int((en - st).total_seconds() // 60)
                            if dur > 0:
                                title = _clean(_TITLE.search(open_blk).group(1)) if _TITLE.search(open_blk) else ""
                                if title:
                                    for key in matched[chan]:
                                        out.setdefault(key, []).append({
                                        "title": title,
                                        "episode_title": "",
                                        "description": _clean(_DESC.search(open_blk).group(1)) if _DESC.search(open_blk) else "",
                                        "season": None,
                                        "episode": None,
                                        "rating": None,
                                        "start_utc": st.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                        "duration_min": dur,
                                        "is_new": False,
                                        "is_live": title.lower().startswith("live"),
                                        "is_repeat": False,
                                    })
                    open_blk = None
                continue
            if "<programme " in line and not variants_done:
                sweep_variants()
                variants_done = True
            if "<channel " in line or "<programme " in line:
                open_blk = line
    if not variants_done:
        sweep_variants()
    for progs in out.values():
        progs.sort(key=lambda p: p["start_utc"])
    return displays, out
