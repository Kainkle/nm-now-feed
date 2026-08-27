"""NTV channel name -> epg.pw channel binding, by normalised name.

The feed's international rows leave `epg_id` empty and let the build resolve it, so a
rename on either side heals on the next build instead of rotting a frozen id. The US
rows keep their curated ids (lineup.py) — those encode judgment calls.

epg.py's scan() does the actual binding (exact normalised match, then a prefix-variant
sweep). This module only builds the `want_norms` table and owns the SYNONYMS the
normaliser cannot derive:

- The RU file's display names are Russian; NTV's are Latin transliterations.
- Some GB display names are compacted ("SkySp Fball HD" for Sky Sports Football).

Every synonym is measured against the real file, not invented — if epg.pw renames one
of these, the build log's per-country MISS line is the tripwire (a channel that had a
schedule and loses it shows up there by name).
"""

from .epg import _norm_key

SYNONYMS: dict[tuple[str, str], list[str]] = {
    # (country, ntv_name) -> extra display names to try, epg.pw spelling
    ("ru", "Match TV"): ["Матч! HD", "Матч ТВ"],
    ("ru", "Match Premier"): ["Матч Премьер"],
    ("ru", "Match Football 1"): ["Матч! Футбол 1"],
    ("ru", "Match Football 2"): ["Матч! Футбол 2"],
    ("ru", "Match Football 3"): ["Матч! Футбол 3"],
    ("gb", "Sky Sports Main Event"): ["SkySp MainEv HD", "SkySp Main HD"],
    ("gb", "Sky Sports Football"): ["SkySp Fball HD"],
    ("gb", "Sky Sports Golf"): ["SkySp Golf HD"],
    ("gb", "Sky Sports Cricket"): ["SkySpCricket HD"],
    ("gb", "Sky Sports Action"): ["SkySp ActionHD"],
    ("gb", "Sky Sports Mix"): ["SkySp Mix HD"],
    ("gb", "Sky Sports F1"): ["SkySp F1"],
    ("gb", "Sky Sports Premier League"): ["SkySp PL HD"],
    ("gb", "Viaplay Sports 1"): ["Viaplay 1"],
    ("gb", "Viaplay Sports 2"): ["Viaplay 2"],
    ("au", "Fox Sports 501 Cricket"): ["FOX CRICKET"],
}


def want_norms(rows: list, country: str) -> dict[str, str]:
    """rows: 7-tuples (ntv, number, display, short, category, epg_cc, epg_id).

    Returns {normalised name: feed number}. Rows with a frozen epg_id are skipped —
    they bind by id, and a second name binding for the same number would be noise.
    """
    out: dict[str, str] = {}
    for r in rows:
        ntv_name, number, epg_cc, epg_id = r[0], r[1], r[5], r[6]
        if epg_cc != country or epg_id:
            continue
        out.setdefault(_norm_key(ntv_name), number)
        for syn in SYNONYMS.get((country.lower(), ntv_name), []):
            out.setdefault(_norm_key(syn), number)
    return out
