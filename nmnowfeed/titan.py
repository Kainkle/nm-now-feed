"""Titan (cdnlive) stream resolver — verified 2026-08-26 against 5 channels, ~1s each.

Chain: catalog `channel_url` (cdnlivetv.tv player page) -> inline script defines a
RANDOM-NAMED base64 decoder and split fragments assembled as `var X=fn(a)+fn(b)...;`
-> decodes to https://cdnlivetv.tv/secure/api/v1/{oid}/playlist.m3u8?token={token}.

The m3u8 is playable with a plain browser UA (no Referer). Tokens live 4 hours;
build.py stamps each resolved stream with minted_utc and carries streams younger
than ~2.5h over between builds, re-resolving only the rest (see build.py — request
volume, not token life, is what sets the rebuild budget).

TRAP: the decoder function name is randomized per page load. Never hardcode it (the
first probe failed exactly this way — NO-ASSEMBLY on every channel). Discover it with
`function (\\w+)\\(s\\)\\{[^}]*atob` every fetch.
"""

import base64
import re
import threading
import time
import urllib.error
import urllib.request

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_DECODER = re.compile(r"function (\w+)\(s\)\{[^}]*atob")
_FRAGS = re.compile(r"var (\w+)='([^']*)'")
_ASSEMBLY = r"%s\((\w+)\)"


def _fetch(url: str, timeout: int = 25, retries: int = 3) -> str:
    """Player-page fetch with 429 backoff — cdnlivetv.tv throttles bursts (measured:
    ~250 rapid requests earn a 429 wall; backing off seconds clears it).

    The read runs on a worker with a whole-transfer deadline: urllib's timeout is per
    blocking op, and cdnlivetv TARPITS datacenter IPs with a byte-drip that keeps every
    op under the cap — measured 2026-08-29/30, every CI build since the 08-28 reorg
    froze here with four workers blocked mid-read and zero output until the 45-min
    workflow wall (run 33281925055's unbuffered log: catalog fetched in 4 s, then
    silence from the first titan resolve). A deadline miss raises, the retry loop backs
    off, and a fully tarpitted IP fails the build fast instead of hanging the cron.
    """
    for attempt in range(retries + 1):
        result: dict = {}

        def _pull() -> None:
            req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
            try:
                result["data"] = urllib.request.urlopen(req, timeout=timeout).read()
            except Exception as e:  # noqa: BLE001 — surfaced to the caller below
                result["err"] = e

        worker = threading.Thread(target=_pull, daemon=True)
        worker.start()
        worker.join(timeout * 2)  # 2x the per-op timeout = the honest-transfer budget
        if "data" in result:
            return result["data"].decode("utf-8", "replace")
        if "err" in result:
            e = result["err"]
            if isinstance(e, urllib.error.HTTPError) and e.code == 429 and attempt < retries:
                time.sleep(1.5 * (attempt + 1) ** 2)  # 1.5s, 6s, 13.5s
                continue
            raise e
        # NOT retried: a drip will not heal in 6s, and retrying it multiplies a
        # tarpitted sweep into hours. The caller (build.py) owns the tier-level
        # circuit breaker this exception arms.
        raise TimeoutError(
            "titan fetch tarpitted: no complete response in %ds (byte-drip under "
            "per-op timeouts)" % (timeout * 2)
        )


def _deob(b64: str) -> str:
    s = b64.replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s).decode("utf-8", "replace")


def resolve(player_url: str) -> str:
    """Return the signed m3u8 URL for a Titan channel player page.

    All 414 catalog URLs point at cdnlivetv.tv, which rate-limits the player route
    brutally (measured 2026-08-26: ~500 requests in an hour walls the IP for hours —
    the homepage still 200s, only the player route 429s). The IDENTICAL page on
    api.cdnlivetv.tv is unthrottled, uses the same atob decoder chain, and mints the
    same 4h tokens bound to the api host. Rewrite before fetching; never hammer the
    apex host again.
    """
    player_url = player_url.replace("://cdnlivetv.tv", "://api.cdnlivetv.tv")
    html = _fetch(player_url)
    fn = _DECODER.search(html).group(1)
    frags = dict(_FRAGS.findall(html))
    m = re.search(r"var \w+=((?:%s\(\w+\)\+?)+);" % fn, html)
    if not m:
        raise ValueError("no assembly line for decoder %r" % fn)
    parts = re.findall(_ASSEMBLY % fn, m.group(1))
    return "".join(_deob(frags[p]) for p in parts)


def stream_ref(player_url: str) -> dict:
    """Resolve into the NM Now feed's StreamRef shape (guide handoff section 4)."""
    return {
        "url": resolve(player_url),
        "type": "hls",
        "referer": "",
        "user_agent": BROWSER_UA,
        "headers": {},
    }
