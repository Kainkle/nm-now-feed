"""Build the bench-box poison feed: #1668 carries an EXPIRED phoenix URL but a live channel_id.

The app should: tune it -> 403 -> NmNowPlayer logs the error -> NmNowPhoenix mints from the box's own
IP -> retunes -> video. If it plays, the in-app resolver is proven end-to-end without waiting 3 hours
for a real token to age out.

Poison = the #1668 stream (url + referer) from feed commit 45795b2, minted 2026-08-28T01:33Z and dead
since ~04:33Z. Everything else (EPG, channel_id, the other 1261 channels) comes from the fresh feed.
#1668 also moves to channels[0] so cold-start focus lands on it and the dwell-tune plays it with zero
d-pad input.
"""
import json
import sys
import urllib.request

NEW = sys.argv[1]          # fresh feed/lineup.json (has resolver + channel_id)
OLD_URL = ("https://raw.githubusercontent.com/Kainkle/nm-now-feed/"
           "45795b2/feed/lineup.json")
OUT = sys.argv[2]

new = json.load(open(NEW, encoding="utf-8"))
old = json.load(urllib.request.urlopen(OLD_URL, timeout=30))

old_stream = next(
    (c["stream"] for c in old["channels"] if c["number"] == "1668"), None)
if not old_stream or "xameleon" not in old_stream.get("url", ""):
    sys.exit("old #1668 stream missing or not phoenix — abort")

target = next((c for c in new["channels"] if c["number"] == "1668"), None)
if not target or (target.get("stream") or {}).get("resolver") != "phoenix":
    sys.exit("new #1668 has no phoenix resolver fields — feed not built with the patch?")

poisoned = dict(target["stream"])
poisoned["url"] = old_stream["url"]
poisoned["referer"] = old_stream["referer"]
target["stream"] = poisoned

new["channels"].remove(target)
new["channels"].insert(0, target)

json.dump(new, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
print(f"poison fed: #1668 first, url={old_stream['url'][:80]}…")
print(f"channel_id kept: {poisoned['channel_id']}, referer={poisoned['referer']}")
