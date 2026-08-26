"""Build the NM Now live feed: NTV (Titan) streams + epg.pw schedules -> feed/lineup.json.

Run: python -m nmnowfeed.build [--out feed] [--catalog snapshot.json]
Without --catalog the NTV catalog is fetched live (their server cache can take ~2min
cold); with it, the build uses a saved snapshot for iteration speed.

Failure policy (mirrors nm-sports-feed CI): any hard failure aborts the build and the
previous published feed stays. Per-channel stream failures only degrade that channel —
it publishes with no stream and heals on the next 30-minute rebuild.
"""

import argparse
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from . import epg, titan
from .lineup import CATEGORIES, LINEUP

CATALOG_URL = "https://ntv.cx/api/get-channels"
CATALOG_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
# Publish window: a little history (so "now playing" is right) plus ~a day and a half ahead.
WINDOW_BACK_MIN = 120
WINDOW_FWD_MIN = 34 * 60


def load_catalog(path: str | None) -> list[dict]:
    if path:
        return json.load(open(path, encoding="utf-8"))["channels"]
    req = urllib.request.Request(CATALOG_URL, headers={"User-Agent": CATALOG_UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))["channels"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="feed")
    ap.add_argument("--catalog", default=None)
    ap.add_argument("--epg-gz", default=None, help="reuse a downloaded EPG snapshot")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    since, until = now - timedelta(minutes=WINDOW_BACK_MIN), now + timedelta(minutes=WINDOW_FWD_MIN)

    catalog = load_catalog(args.catalog)
    titan_us = {c["channel_name"]: c for c in catalog if c["server"] == "cdnlive" and c.get("channel_code") == "us"}
    print("catalog: %d channels, %d titan-us" % (len(catalog), len(titan_us)))

    curated = {name for name, *_ in LINEUP}
    uncatalogued = sorted(curated - set(titan_us))
    uncurated = sorted(set(titan_us) - curated)
    if uncatalogued:
        print("MISSING from catalog (dropped this build): %s" % ", ".join(uncatalogued))
    if uncurated:
        print("catalog titan-us channels not curated (intentional skips): %s" % ", ".join(uncurated))

    # --- streams (Titan pages resolve ~1s each; 8 workers keeps a full build under ~30s) ---
    rows = [r for r in LINEUP if r[0] in titan_us]

    def resolve_row(r):
        name = r[0]
        try:
            return name, titan.stream_ref(titan_us[name]["channel_url"])
        except Exception as e:  # noqa: BLE001 — any channel failure degrades that channel only
            print("stream FAIL %s: %s" % (name, str(e)[:120]))
            return name, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        streams = dict(pool.map(resolve_row, rows))
    ok = sum(1 for v in streams.values() if v)
    print("streams: %d/%d resolved" % (ok, len(rows)))

    # --- EPG ---
    wanted = {r[5] for r in rows if r[5]}
    gz = args.epg_gz or os.path.join(args.out, ".epg_US.xml.gz.tmp")
    if not args.epg_gz:
        os.makedirs(args.out, exist_ok=True)
        print("downloading %s ..." % epg.EPG_URL)
        epg.fetch(gz)
    progs = epg.programmes(gz, wanted, since, until)
    if args.epg_gz is None:
        os.unlink(gz)
    mapped = sum(1 for v in progs.values() if v)
    total_progs = sum(len(v) for v in progs.values())
    print("epg: %d/%d mapped ids carry programmes in window, %d rows" % (mapped, len(wanted), total_progs))

    # Drift tripwire for the EPG_WALL_TZ_HOURS correction (see epg.py): print what three
    # well-known channels claim is airing AT THIS MINUTE. Eyeball it against reality --
    # a morning build saying "Jesse Watters Primetime" / an evening build saying
    # "Fox & Friends" means the source's stamps moved and the constant needs re-measuring.
    ANCHORS = {"465372": "FOX News", "465198": "ESPN", "464902": "ABC"}
    for cid, name in ANCHORS.items():
        for p in progs.get(cid, []):
            st = datetime.strptime(p["start_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if st <= now < st + timedelta(minutes=p["duration_min"]):
                print("anchor %-9s airing now: %s" % (name, p["title"]))
                break

    # --- emit ---
    channels = []
    gap_notes = 0
    for ntv_name, number, display, short, cat, epg_id in sorted(rows, key=lambda r: r[1]):
        plist = progs.get(epg_id, []) if epg_id else []
        # Clip the leading/trailing rows to the window so the row is flush with the timeline.
        plist = [dict(p) for p in plist]
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
            "logo_url": titan_us[ntv_name].get("channel_image") or "",
            "stream": streams.get(ntv_name),
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
    print("wrote %s: %d channels, %d programmes, %d gap notes, %.0f KB"
          % (out_path, len(channels), total_progs, gap_notes, os.path.getsize(out_path) / 1024))
    if not channels:
        print("EMPTY FEED — refusing to consider this a success")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
