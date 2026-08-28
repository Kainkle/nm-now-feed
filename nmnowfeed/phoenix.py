"""Phoenix (dlhd) stream resolver — chain re-verified 2026-08-28 against Cartoon Network (id 339).

dlhd moved the TV tier overnight 2026-08-27/28: the old /stream/stream-{id}.php pages 404
and the ids rotated wholesale (Cartoon Network 1317->339, Adult Swim 1234->295). The new
door is watch.php:

    dlhd.st/watch.php?id={id}            (Referer https://dlhd.st/24-7-channels.php)
      -> iframe -> dlstreams.st/stream/stream-{id}.php   (Referer = the watch.php URL)
      -> iframe -> https://{shard}.romponalis.st/premiumtv/daddy.php?id={id}
                   (Referer = the dlstreams stream page URL)
      -> 200 tiny page whose SINGLE literal atob('...') decodes to the master m3u8
      -> master 200s only with Referer = the daddy shard origin (else 403 Invalid Referer)

Traps paid for already (do not relearn):
- The daddy shard host ROTATES (hamis. tonight, others other nights). Never hardcode;
  read it out of the dlstreams page every resolve.
- The watch.php id space is NOT stable across dlhd reorgs — see remap_ids(); the ntv.cx
  catalog still carries the OLD ids, so every build re-anchors them to the live
  24-7-channels.php listing by normalized name.
- VERIFY the master starts '#EXTM3U' — a rotated/stale shard can 200 with junk, and a
  2.5h-carried token can silently expire one rebuild early without it.
- TTL is exactly 180 min: the secure path embeds the unix expiry. build.py's 150-min
  carry window leaves the same safety margin Titan uses.
- Segments are presigned; only the master (and the variant playlists it names) need
  the referer. The app's DefaultHttpDataSource already carries StreamRef.referer.
"""

import base64
import re
import time
import urllib.error
import urllib.request

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
LIST_REFERER = "https://dlhd.st/24-7-channels.php"
WATCH_PAGE = "https://dlhd.st/watch.php?id=%s"

_IFRAME = re.compile(r'<iframe[^>]+src="(https?://[^"]+)"')
_DADDY = re.compile(r'https?://[^"]+/daddy\d*\.php\?id=\d+[^"]*')
_ATOB = re.compile(r"atob\(\s*['\"]([A-Za-z0-9+/=]{30,})['\"]\s*\)")


def _fetch(url: str, referer: str | None = None, timeout: int = 25, retries: int = 2) -> str:
    """GET with UA/referer; 429/5xx backoff (same shape as titan._fetch)."""
    for attempt in range(retries + 1):
        headers = {"User-Agent": BROWSER_UA}
        if referer:
            headers["Referer"] = referer
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=timeout
            ).read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and attempt < retries:
                time.sleep(1.5 * (attempt + 1) ** 2)
                continue
            raise


def live_ids() -> dict[str, str]:
    """{normalized data-title: live watch.php id} scraped from the 24-7 listing.

    One GET per build. This is the ONLY id source of truth now: the ntv.cx catalog's
    dlhd ids are the pre-reorg space and resolve to 404s or to unrelated event pages.
    """
    page = _fetch(LIST_REFERER, timeout=30)
    out: dict[str, str] = {}
    for a in re.finditer(r'<a class="card"[^>]*>', page):
        tag = a.group(0)
        idm = re.search(r'id=(\d+)', tag)
        tm = re.search(r'data-title="([^"]+)"', tag)
        if idm and tm:
            out[norm(tm.group(1))] = idm.group(1)
    return out


def norm(n: str) -> str:
    n = re.sub(r"[^\w]+", " ", n.lower()).strip()
    return re.sub(r"\s+(hd|sd|fhd|uhd)$", "", n)


def resolve(channel_id: str) -> tuple[str, str]:
    """Return (master_m3u8_url, daddy_origin_referer) for a live watch.php channel id.

    Raises ValueError on any break in the chain — the caller degrades that channel
    only, exactly like titan.resolve failures.
    """
    watch = WATCH_PAGE % channel_id
    page = _fetch(watch, referer=LIST_REFERER)
    dlstreams = next(
        (u for u in _IFRAME.findall(page) if "dlstreams.st" in u), ""
    )
    if not dlstreams:
        raise ValueError("no dlstreams iframe in watch page")

    stream_page = _fetch(dlstreams, referer=watch)
    daddy = _DADDY.search(stream_page)
    if not daddy:
        raise ValueError("no daddy iframe in stream page")

    body = _fetch(daddy.group(0), referer=dlstreams)
    a = _ATOB.search(body)
    if not a:
        raise ValueError("no atob payload on daddy page")
    master = base64.b64decode(a.group(1)).decode("utf-8", "replace").strip()
    if not master.startswith("http"):
        raise ValueError("atob did not decode to a URL")

    daddy_origin = "/".join(daddy.group(0).split("/")[:3])
    head = _fetch(master, referer=daddy_origin, timeout=15)
    if not head.lstrip().startswith("#EXTM3U"):
        raise ValueError("master is not EXTM3U (rotated shard?)")
    return master, daddy_origin


def stream_ref(channel_id: str) -> dict:
    """Resolve into the NM Now feed's StreamRef shape (referer is load-bearing here).

    resolver/channel_id ride along so the APP can re-mint this StreamRef itself when the carried
    URL is dead where it's being played (xameleon masters are IP-bound to the minting machine and
    expire in 180 min — measured 2026-08-27/28). An app that ignores the fields loses nothing.
    """
    url, ref = resolve(channel_id)
    return {
        "url": url,
        "type": "hls",
        "referer": ref,
        "user_agent": BROWSER_UA,
        "headers": {},
        "resolver": "phoenix",
        "channel_id": channel_id,
    }
