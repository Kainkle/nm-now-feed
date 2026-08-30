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
    # (country, _norm_key(ntv_name)) -> extra display names to try, epg.pw spelling.
    # Keys are NORMALISED, not raw: the AU table was once keyed "Fox Sports 501
    # Cricket" and died silently when the row renamed to "Fox Sports 501" — and
    # dlhd twins spell the same channel differently ("FOX Sports 502"). A norm
    # key covers every spelling that normalises the same.
    ("ru", "matchtv"): ["Матч! HD", "Матч ТВ"],
    ("ru", "matchpremier"): ["Матч Премьер"],
    ("ru", "matchfootball1"): ["Матч! Футбол 1"],
    ("ru", "matchfootball2"): ["Матч! Футбол 2"],
    ("ru", "matchfootball3"): ["Матч! Футбол 3"],
    ("gb", "skysportsmainevent"): ["SkySp MainEv HD", "SkySp Main HD", "SkySpMainEvHD"],
    ("gb", "skysportsfootball"): ["SkySp Fball HD"],
    ("gb", "skysportsgolf"): ["SkySp Golf HD"],
    ("gb", "skysportscricket"): ["SkySpCricket HD"],
    ("gb", "skysportsaction"): ["SkySp ActionHD"],
    ("gb", "skysportsmix"): ["SkySp Mix HD"],
    ("gb", "skysportsf1"): ["SkySp F1"],
    ("gb", "skysportspremierleague"): ["SkySp PL HD"],
    ("gb", "skysportsarena"): ["SkySp ArenaHD"],
    ("gb", "skysportsracing"): ["SkySp Racing HD"],
    ("gb", "skysportstennis"): ["SkySp Tennis HD"],
    ("gb", "skysportsnews"): ["SkySp News HD"],
    ("gb", "skycinemagreats"): ["Sky Greats HD"],
    ("gb", "viaplaysports1"): ["Viaplay 1"],
    ("gb", "viaplaysports2"): ["Viaplay 2"],
    ("au", "foxsports501"): ["FOX CRICKET"],
    ("au", "foxsports501cricket"): ["FOX CRICKET"],
    ("au", "foxsports502"): ["FOX League"],
    ("au", "foxsports504"): ["FOX Footy"],
    ("au", "foxsports507"): ["Fox Sports More"],
    # The US file carries no national FOX / MAX / A&E — leave those honestly
    # unbound rather than binding a wrong channel. ABC's twin can't sweep-bind
    # ("abc" is under the 6-char prefix floor), so it goes through explicitly.
    ("us", "abc"): ["ABC National Feed"],
    ("us", "wwe"): ["WWE Network"],
    # Disney JR normalises to "disneyjr" — 8 chars, but the file's variants
    # ("Disney Junior HD" / "Disney Junior HD (Pacific)") normalise to
    # "disneyjunior..." — the exact-match fails and the prefix sweep compares
    # in the wrong direction. Measured against epg_US 2026-08-29: the HD feed
    # is the national one. (Universal Kids and POP TV are NOT in the file at
    # all — those stay honestly unbound.)
    ("us", "disneyjr"): ["Disney Junior HD"],
    # CA's file is affiliate-based; the national rows take the Toronto flagship.
    ("ca", "cbc"): ["CBC Toronto HD"],
    ("ca", "ctv"): ["CTV Toronto HD"],
    ("ca", "ctv2"): ["CTV Two - Toronto"],
    # BR Premiere/Globo are city-prefixed ("São Paulo/SP  Premiere 7"); the plain
    # norms can never collide. Premiere 1/4 and Globo RIO have no file entry.
    ("br", "premiere2"): ["São Paulo/SP  Premiere 2"],
    ("br", "premiere3"): ["São Paulo/SP  Premiere 3"],
    ("br", "premiere5"): ["São Paulo/SP  Premiere 5"],
    ("br", "premiere6"): ["São Paulo/SP  Premiere 6"],
    ("br", "premiere7"): ["São Paulo/SP  Premiere 7"],
    ("br", "globosp"): ["São Paulo/SP  Globo"],
    # dlhd's plain NICK normalises to "nick" -- 4 chars, under the 6-char prefix
    # floor, so it can never sweep-bind the file's "Nickelodeon HD". Measured
    # against epg_US 2026-08-29: 'Nickelodeon HD' and 'Nickelodeon (Pacific)'
    # both present; the HD feed is the national one we want.
    ("us", "nick"): ["Nickelodeon HD"],
}


def want_norms(rows: list, country: str) -> dict[str, list[str]]:
    """rows: 7-tuples (ntv, number, display, short, category, epg_cc, epg_id).

    Returns {normalised name: [feed numbers]}. Rows with a frozen epg_id are
    skipped — they bind by id, and a second name binding for the same number
    would be noise. A norm carries a LIST because the dlhd tier twins cdnlive
    channels under cleaned names ("BBC One UK" -> "BBC One"): both rows deserve
    the schedule the name binds to, and epg.py fans one epg id out to all of
    them. Order is rows order — cdnlive numbers first, which the variant sweep
    treats as priority.
    """
    out: dict[str, list[str]] = {}

    def _add(norm: str, number: str) -> None:
        nums = out.setdefault(norm, [])
        if number not in nums:
            nums.append(number)

    for r in rows:
        ntv_name, number, epg_cc, epg_id = r[0], r[1], r[5], r[6]
        if epg_cc != country or epg_id:
            continue
        _add(_norm_key(ntv_name), number)
        for syn in SYNONYMS.get((country.lower(), _norm_key(ntv_name)), []):
            _add(_norm_key(syn), number)
    return out
