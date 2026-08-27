"""Phoenix (dlhd) stream resolver — chain re-verified 2026-08-27 against Cartoon Network.

The ntv.cx/channel/phoenix/{id} page only names the brand; the chain itself needs no
ntv page at all:

    dlhd.st/stream/stream-{id}.php   (Referer https://ntv.cx/)
      -> 301 -> dlstreams.st/stream/stream-{id}.php
      -> 200 page whose iframe is https://{shard}.romponalis.st/premiumtv/daddy.php?id={id}
      -> 200 tiny page whose SINGLE literal atob('...') decodes to the master m3u8
      -> master 200s only with Referer = the daddy shard origin (else 403 Invalid Referer)

Traps paid for already (do not relearn):
- The daddy shard host ROTATES (hamis. tonight, others other nights). Never hardcode;
  read it out of the dlstreams page every resolve.
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
NTV_REFERER = "https://ntv.cx/"
STREAM_PAGE = "https://dlhd.st/stream/stream-%s.php"

_IFRAME = re.compile(r'<iframe[^>]+src="(https?://[^"]+/daddy\d*\.php\?id=\d+[^"]*)"')
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


def resolve(channel_id: str) -> tuple[str, str]:
    """Return (master_m3u8_url, daddy_origin_referer) for a dlhd channel id.

    Raises ValueError on any break in the chain — the caller degrades that channel
    only, exactly like titan.resolve failures.
    """
    page = _fetch(STREAM_PAGE % channel_id, referer=NTV_REFERER)  # 301 to dlstreams followed
    m = _IFRAME.search(page)
    if not m:
        raise ValueError("no daddy iframe in stream page")
    daddy = m.group(1)

    body = _fetch(daddy, referer="https://dlstreams.st/stream/stream-%s.php" % channel_id)
    a = _ATOB.search(body)
    if not a:
        raise ValueError("no atob payload on daddy page")
    master = base64.b64decode(a.group(1)).decode("utf-8", "replace").strip()
    if not master.startswith("http"):
        raise ValueError("atob did not decode to a URL")

    daddy_origin = "/".join(daddy.split("/")[:3])
    head = _fetch(master, referer=daddy_origin, timeout=15)
    if not head.lstrip().startswith("#EXTM3U"):
        raise ValueError("master is not EXTM3U (rotated shard?)")
    return master, daddy_origin


def stream_ref(channel_id: str) -> dict:
    """Resolve into the NM Now feed's StreamRef shape (referer is load-bearing here)."""
    url, ref = resolve(channel_id)
    return {
        "url": url,
        "type": "hls",
        "referer": ref,
        "user_agent": BROWSER_UA,
        "headers": {},
    }
