"""Titan (cdnlive) stream resolver — verified 2026-08-26 against 5 channels, ~1s each.

Chain: catalog `channel_url` (cdnlivetv.tv player page) -> inline script defines a
RANDOM-NAMED base64 decoder and split fragments assembled as `var X=fn(a)+fn(b)...;`
-> decodes to https://cdnlivetv.tv/secure/api/v1/{oid}/playlist.m3u8?token={token}.

The m3u8 is playable with a plain browser UA (no Referer). Tokens live 4 hours, which
is why the feed rebuilds every 30 minutes — a published URL is never more than ~35
minutes old in practice.

TRAP: the decoder function name is randomized per page load. Never hardcode it (the
first probe failed exactly this way — NO-ASSEMBLY on every channel). Discover it with
`function (\\w+)\\(s\\)\\{[^}]*atob` every fetch.
"""

import base64
import re
import urllib.request

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_DECODER = re.compile(r"function (\w+)\(s\)\{[^}]*atob")
_FRAGS = re.compile(r"var (\w+)='([^']*)'")
_ASSEMBLY = r"%s\((\w+)\)"


def _fetch(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")


def _deob(b64: str) -> str:
    s = b64.replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s).decode("utf-8", "replace")


def resolve(player_url: str) -> str:
    """Return the signed m3u8 URL for a Titan channel player page."""
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
