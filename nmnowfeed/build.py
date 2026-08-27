"""Build the NM Now live feed: NTV (Titan) streams + epg.pw schedules -> feed/lineup.json.

Run: python -m nmnowfeed.build [--out feed] [--catalog snapshot.json] [--epg-dir DIR]
Without --catalog the NTV catalog is fetched live (their server cache can take ~2min
cold); with it, the build uses a saved snapshot for iteration speed. --epg-dir points
at a cache of epg_CC.xml.gz snapshots; a file younger than 6h is reused instead of
re-fetched (CI simply passes nothing and downloads everything fresh).

Failure policy (mirrors nm-sports-feed CI): any hard failure aborts the build and the
previous published feed stays. Per-channel stream failures only degrade that channel —
it publishes with no stream and heals on the next 30-minute rebuild. The per-country
timezone ANCHORS are hard failures: a wrong schedule for a whole country is exactly
the "wrong region" bug this pipeline already paid for once.
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from . import epg, matching, titan
from .lineup import CATEGORIES, LINEUP, LINEUP_INTL

CATALOG_URL = "https://ntv.cx/api/get-channels"
CATALOG_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
# Publish window: a little history (so "now playing" is right) plus ~a day and a half ahead.
WINDOW_BACK_MIN = 120
WINDOW_FWD_MIN = 34 * 60
EPG_CACHE_MAX_AGE_S = 6 * 3600

# One self-titled show per epg.pw file, with the UTC minute-of-day its NAME promises.
# "News at One" must land at 12:00Z (13:00 BST), Tagesthemen at 20:15Z, and so on. If
# epg.pw ever changes a file's stamps, one of these lands >45min off its own name and
# the build refuses to publish. Instances are matched by title substring on today's
# UTC date; weekend gaps ("no instance today") only warn.
#   (country, epg_id, title-substring, expected_utc_minute, note)
ANCHORS = [
    ("US", "464902", "World News Tonight", 22 * 60 + 30, "ABC 18:30 ET"),
    ("GB", "12385", "News at One", 12 * 60, "BBC 13:00 BST"),
    ("DE", "76674", "Tagesthemen", 20 * 60 + 15, "22:15 CEST"),
    ("FR", "55812", "Journal 20h", 18 * 60, "20:00 CEST"),
    ("AU", "40933", "Seven News At 4", 6 * 60, "16:00 AEST"),
    ("NZ", "2360", "1News at Six", 7 * 60, "19:00 NZST on the +1 feed"),
    ("BR", "523353", "Jornal Nacional", 23 * 60 + 30, "20:30 BRT"),
    ("CA", "470299", "Global News at 6", 22 * 60, "18:00 ET"),
    ("RU", "5899", "Вести", 13 * 60, "20:00 on Россия 1 +4"),
]
# A whole-file stamp flip moves an anchor by hours; live sport moves a bulletin by
# under ninety minutes (Globo's Jornal Nacional starts early on midweek football
# nights — measured 2026-08-26: 22:40Z instead of 23:30Z). 2h splits the two cleanly.
# The instance checked is the one CLOSEST to the promised time-of-day, because most
# anchors are bulletins that air several editions a day (Вести runs seven).
ANCHOR_TOLERANCE_MIN = 120


def _circular_min_delta(a: int, b: int) -> int:
    d = abs(a - b) % 1440
    return min(d, 1440 - d)


def load_catalog(path: str | None) -> list[dict]:
    if path:
        return json.load(open(path, encoding="utf-8"))["channels"]
    req = urllib.request.Request(CATALOG_URL, headers={"User-Agent": CATALOG_UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))["channels"]


def get_epg_gz(country: str, epg_dir: str) -> str:
    """Return a local epg_{CC}.xml.gz path, downloading only if the cache is stale."""
    path = os.path.join(epg_dir, "epg_%s.xml.gz" % country)
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < EPG_CACHE_MAX_AGE_S:
        return path
    os.makedirs(epg_dir, exist_ok=True)
    tmp = path + ".tmp"
    print("downloading epg_%s ..." % country)
    epg.fetch(tmp, country)
    os.replace(tmp, path)
    return path


def main() -> int:
    # epg.pw carries Cyrillic titles and our own logs name them; a Windows console
    # defaults to cp1252 and dies mid-build on the first one.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="feed")
    ap.add_argument("--catalog", default=None)
    ap.add_argument("--epg-dir", default=None, help="cache dir for epg_CC.xml.gz (default <out>/.epg)")
    args = ap.parse_args()
    epg_dir = args.epg_dir or os.path.join(args.out, ".epg")

    now = datetime.now(timezone.utc)
    since, until = now - timedelta(minutes=WINDOW_BACK_MIN), now + timedelta(minutes=WINDOW_FWD_MIN)

    catalog = load_catalog(args.catalog)
    titan_by = {}
    dupes = 0
    for c in catalog:
        if c["server"] != "cdnlive":
            continue
        key = (c["channel_code"], c["channel_name"])
        if key in titan_by:
            dupes += 1
        titan_by[key] = c
    print("catalog: %d channels, %d titan rows (%d duplicate names collapsed)"
          % (len(catalog), len(titan_by), dupes))

    rows = LINEUP + LINEUP_INTL
    catalog_us = {name for (cc, name) in titan_by if cc == "us"}
    uncurated = catalog_us - {r[0] for r in LINEUP}
    if uncurated:
        print("catalog titan-us channels not curated (intentional skips): %s" % ", ".join(sorted(uncurated)))
    missing = [r for r in rows if (r[5].lower(), r[0]) not in titan_by]
    if missing:
        print("lineup rows MISSING from catalog (skipped this build): %s"
              % ", ".join("%s/%s" % (r[5], r[0]) for r in missing))

    # --- streams (Titan pages resolve ~1s each; 8 workers keeps a full build under ~2min) ---
    # Keyed by feed number: channel names repeat across countries ("ESPN" exists in five).
    #
    # Titan tokens live 4h, so streams from the previous published feed younger than
    # 150min are carried over instead of re-resolved — a 30-min rebuild then touches
    # only the channels crossing the age line (~80 requests), not all 411. Measured
    # 2026-08-26: cdnlivetv.tv walls the IP somewhere near ~500 requests/hour, and a
    # full sweep per build (822/hr) sat right on that ceiling. A stream 150-200min
    # old is past the carry line but still alive, so a failed resolve falls back to
    # it rather than publishing the channel with no stream.
    STREAM_REUSE_MAX_AGE_MIN = 150
    STREAM_FALLBACK_MAX_AGE_MIN = 200

    def _prev_age(st: dict) -> float | None:
        try:
            minted = datetime.strptime(st["minted_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            return None
        return (now - minted).total_seconds() / 60

    carry: dict[str, dict] = {}
    fallback: dict[str, dict] = {}
    prev_path = os.path.join(args.out, "lineup.json")
    if os.path.exists(prev_path):
        try:
            with open(prev_path, encoding="utf-8") as f:
                for ch in json.load(f).get("channels", []):
                    st = ch.get("stream")
                    if not (st and st.get("url")):
                        continue
                    age = _prev_age(st)
                    if age is None or age < 0:
                        continue
                    if age < STREAM_REUSE_MAX_AGE_MIN:
                        carry[ch["number"]] = st
                    elif age < STREAM_FALLBACK_MAX_AGE_MIN:
                        fallback[ch["number"]] = st
        except (ValueError, OSError):
            pass  # unreadable previous feed — resolve everything fresh

    now_s = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    def resolve_row(r):
        number, name, cc = r[1], r[0], r[5].lower()
        if number in carry:
            return number, carry[number]
        entry = titan_by.get((cc, name))
        if entry is None:
            return number, None
        time.sleep(0.15)  # pacing — see the workers comment below
        try:
            st = titan.stream_ref(entry["channel_url"])
            st["minted_utc"] = now_s
            return number, st
        except Exception as e:  # noqa: BLE001 — any channel failure degrades that channel only
            print("stream FAIL %s/%s: %s" % (cc, name, str(e)[:120]))
            return number, fallback.get(number)

    # 4 workers + a short pause per request: a full 411-channel sweep is a once-ever
    # event now (steady state re-resolves ~80), and the one sweep that earned the
    # original 429 wall was 8 unpaced workers. Gentle costs ~30 extra seconds.
    with ThreadPoolExecutor(max_workers=4) as pool:
        streams = dict(pool.map(resolve_row, rows))

    ok = sum(1 for v in streams.values() if v)
    print("streams: %d/%d up (%d carried from previous feed, %d resolved fresh)"
          % (ok, len(rows), len(carry), ok - len(carry)))

    # --- EPG: one pass per country file ---
    # progs_by_number: feed number -> programme list; anchor_ids ride along as
    # "ANCHOR-{CC}" keys so the timezone check shares the single streaming pass.
    progs_by_number: dict[str, list[dict]] = {}
    anchor_fail = False

    for country, wall_hours in epg.EPG_COUNTRIES.items():
        rows_cc = [r for r in rows if r[5] == country]
        want_ids = {r[6]: r[1] for r in rows_cc if r[6]}
        # Anchors bind alongside the rows, never instead of them (an anchor stealing
        # a curated id once silently dropped ABC's whole schedule and its own check).
        anchor_ids = {aid: "ANCHOR-%s" % country for cc, aid, _, _, _ in ANCHORS if cc == country}
        norms = matching.want_norms(rows_cc, country)
        if not want_ids and not norms and not anchor_ids:
            continue
        gz = get_epg_gz(country, epg_dir)
        displays, progs = epg.scan(gz, norms, want_ids, anchor_ids, since, until, wall_hours)
        got = set(progs.keys())
        matched_rows = sum(1 for r in rows_cc if r[1] in got)
        miss_names = [r[0] for r in rows_cc if r[1] not in got]
        print("epg %s: %d/%d channels carry programmes%s"
              % (country, matched_rows, len(rows_cc),
                 ("; MISS: " + ", ".join(miss_names[:12]) + (" +%d" % (len(miss_names) - 12) if len(miss_names) > 12 else "")) if miss_names else ""))
        for number, plist in progs.items():
            if number.startswith("ANCHOR-"):
                continue
            progs_by_number.setdefault(number, []).extend(plist)

        # timezone anchors: the first instance of a self-titled show inside the window
        # vs what its own name promises. Not "today's instance" — a build run in the
        # evening has already lost today's morning shows to WINDOW_BACK, and the
        # promised clock time is the same every day the show runs.
        for cc, aid, title_sub, expected_min, note in ANCHORS:
            if cc != country:
                continue
            plist = progs.get("ANCHOR-%s" % cc, [])
            hits = [p for p in plist if title_sub.lower() in p["title"].lower()]
            if not hits:
                print("anchor %-2s %-18s no instance in window (WARN only)" % (cc, title_sub))
                continue
            def _dist(p):
                st = datetime.strptime(p["start_utc"], "%Y-%m-%dT%H:%M:%SZ")
                return _circular_min_delta(st.hour * 60 + st.minute, expected_min)
            best = min(hits, key=_dist)
            st = datetime.strptime(best["start_utc"], "%Y-%m-%dT%H:%M:%SZ")
            got_min = st.hour * 60 + st.minute
            delta = _circular_min_delta(got_min, expected_min)
            mark = "ok" if delta <= ANCHOR_TOLERANCE_MIN else "DRIFT"
            print("anchor %-2s %-18s %s %02d:%02dZ, name promises %02d:%02dZ (%s) -> %s"
                  % (cc, title_sub, st.date(), st.hour, st.minute, expected_min // 60,
                     expected_min % 60, note, mark))
            if delta > ANCHOR_TOLERANCE_MIN:
                anchor_fail = True

    if anchor_fail:
        print("ANCHOR DRIFT — a country's stamps moved; refusing to publish (previous feed stays)")
        return 1

    mapped = sum(1 for r in rows if progs_by_number.get(r[1]))
    total_progs = sum(len(v) for v in progs_by_number.values())
    print("epg total: %d/%d channels carry programmes, %d rows" % (mapped, len(rows), total_progs))

    # --- emit ---
    channels = []
    gap_notes = 0
    for row in sorted(rows, key=lambda r: int(r[1])):
        ntv_name, number, display, short, cat, cc, epg_id = row
        entry = titan_by.get((cc.lower(), ntv_name))
        if entry is None:
            print("row %s %s: not in catalog — SKIPPED" % (number, ntv_name))
            continue
        plist = [dict(p) for p in progs_by_number.get(number, [])]
        stream = streams.get(number)
        # Clip the leading rows to the window so the row is flush with the timeline.
        for p in plist:
            st = datetime.strptime(p["start_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            en = st + timedelta(minutes=p["duration_min"])
            if st < since:
                p["start_utc"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")
                p["duration_min"] = int((en - since).total_seconds() // 60)
        for p in plist:
            p["id"] = "%s-%s" % (number, p["start_utc"])
            p.pop("start", None)
        prev_end = None
        for p in plist:
            st = datetime.strptime(p["start_utc"], "%Y-%m-%dT%H:%M:%SZ")
            if prev_end and st != prev_end:
                gap_notes += 1
            prev_end = st + timedelta(minutes=p["duration_min"])
        channels.append({
            "number": number,
            "name": display,
            "short": short,
            "category": cat,
            "favorite": False,
            "logo_url": entry.get("channel_image") or "",
            "stream": stream,
            "programmes": plist,
        })

    doc = {
        "meta": {"source": "live", "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
        "categories": (
            [{"id": "recents", "label": "Recents", "icon": "recents"},
             {"id": "favorites", "label": "Favorites", "icon": "favorites", "dividerAfter": True}]
            + [{"id": i, "label": l, "icon": ic} for i, l, ic in CATEGORIES]
            + [{"id": "all", "label": "All Channels", "icon": "all"}]
        ),
        "channels": channels,
    }
    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, "lineup.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    size_kb = os.path.getsize(out_path) / 1024
    print("wrote %s: %d channels, %d programmes, %d gap notes, %.0f KB%s"
          % (out_path, len(channels), total_progs, gap_notes, size_kb,
             "  (!! > 6 MB — trim the window)" if size_kb > 6 * 1024 else ""))
    if not channels:
        print("EMPTY FEED — refusing to consider this a success")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
