"""epg.pw XMLTV ingest.

Source of truth for schedules: https://epg.pw/xmltv/epg_US.xml.gz (~21MB gz, ~160MB XML,
5,467 channels, 7-day depth). The builder downloads it fresh each run and streams out
only the programmes belonging to channels in the curated lineup's epg-id set.

epg.pw carries title + desc only — no sub-title/episode/rating/new flags. `is_live` is
derived from the "Live: " title prefix, which epg.pw uses consistently for live sport
and talk coverage.
"""

import gzip
import re
import urllib.request
from datetime import datetime, timedelta, timezone

EPG_URL = "https://epg.pw/xmltv/epg_US.xml.gz"

# epg.pw's US file stamps wall times in UTC+8 while labelling every attribute "+0000".
# Measured 2026-08-26 against the real US/Eastern broadcast day, 12+ anchors across three
# channels, every one exactly +8h and none off-pattern:
#   FNC Jesse Watters   really 8:00pm  ET = 00:00Z -> stamped 20260826080000 +0000
#   FNC The Five        really 5:00pm  ET = 21:00Z -> stamped 20260826050000 +0000
#   ESPN Get Up         really 8:00am  ET = 12:00Z -> stamped 20260826200000 +0000
#   ABC  Kimmel         really 11:35pm ET = 03:35Z -> stamped 20260826113500 +0000
#   FNC Faulkner Focus  really 11:00am ET = 15:00Z -> stamped 20260826230000 +0000
# (epg.pw is an APAC-operated aggregator; their web UI offers a timezone selector but the
# XMLTV endpoints are static files with no tz parameter -- there is no correct-UTC file.)
# If they ever fix the stamps, build.py's ANCHORS log line will show every anchor ~8h
# displaced and this constant goes to 0.
EPG_WALL_TZ_HOURS = 8

_PROG_OPEN = re.compile(r"<programme ([^>]*)>")
# Attribute order inside <programme> varies (channel-first in the wild) — never assume.
_ATTR = lambda tag, name: re.search(r'%s="([^"]*)"' % name, tag)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
_DESC = re.compile(r"<desc[^>]*>(.*?)</desc>", re.S)
_TAG = re.compile(r"<[^>]+>")


def _as_utc(stamp: str, offset: str | None) -> datetime:
    dt = datetime.strptime(stamp, "%Y%m%d%H%M%S")
    if offset:
        sign = 1 if offset[0] == "+" else -1
        dt = dt.replace(tzinfo=timezone(sign * timedelta(hours=int(offset[1:3]), minutes=int(offset[3:5]))))
    else:
        dt = dt.replace(tzinfo=timezone.utc)
    # The source's wall times are UTC+8 despite the +0000 label -- see EPG_WALL_TZ_HOURS.
    return dt.astimezone(timezone.utc) - timedelta(hours=EPG_WALL_TZ_HOURS)


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return _TAG.sub("", text).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">") \
        .replace("&quot;", '"').replace("&apos;", "'").strip()


def fetch(path: str) -> None:
    """Download the gz snapshot to `path`."""
    req = urllib.request.Request(EPG_URL, headers={"User-Agent": "nm-now-feed/1.0"})
    with urllib.request.urlopen(req, timeout=300) as r, open(path, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)


def programmes(gz_path: str, wanted: set[str], since: datetime, until: datetime) -> dict[str, list[dict]]:
    """Stream the gz and return {epg_channel_id: [programme dict, ...]} for `wanted`.

    Programme dicts are feed-ready (handoff section 2.2) except `id`, which build.py
    prefixes with the channel number.
    """
    out: dict[str, list[dict]] = {cid: [] for cid in wanted}
    open_prog = None  # accumulating programme block text

    with gzip.open(gz_path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            if open_prog is not None:
                open_prog += line
                if "</programme>" in line:
                    m = open_prog
                    open_prog = None
                    om = _PROG_OPEN.search(m)
                    if not om:
                        continue
                    attrs = om.group(1)
                    chan_m = _ATTR(attrs, "channel")
                    start_m, stop_m = _ATTR(attrs, "start"), _ATTR(attrs, "stop")
                    if not (chan_m and start_m and stop_m):
                        continue
                    chan = chan_m.group(1)
                    if chan not in wanted:
                        continue
                    try:
                        sm = re.match(r"(\d{14})\s*([+-]\d{4})?", start_m.group(1))
                        em = re.match(r"(\d{14})\s*([+-]\d{4})?", stop_m.group(1))
                        st = _as_utc(sm.group(1), sm.group(2))
                        en = _as_utc(em.group(1), em.group(2))
                    except ValueError:
                        continue
                    if en <= since or st >= until:
                        continue
                    dur = int((en - st).total_seconds() // 60)
                    if dur <= 0:
                        continue
                    title = _clean(_TITLE.search(m).group(1)) if _TITLE.search(m) else ""
                    if not title:
                        continue
                    out[chan].append({
                        "title": title,
                        "episode_title": "",
                        "description": _clean(_DESC.search(m).group(1)) if _DESC.search(m) else "",
                        "season": None,
                        "episode": None,
                        "rating": None,
                        "start_utc": st.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        # Trim to the window edges so the row is flush with the timeline.
                        "duration_min": dur,
                        "is_new": False,
                        "is_live": title.lower().startswith("live"),
                        "is_repeat": False,
                    })
                continue
            if "<programme " in line:
                open_prog = line
    for progs in out.values():
        progs.sort(key=lambda p: p["start_utc"])
    return out
