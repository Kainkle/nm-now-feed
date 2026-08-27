"""dlhd (Phoenix) lineup generator — the 900-channel tier, generated from the catalog.

dlhd catalog rows carry only channel_id + name (no url, no country code). Every
curation axis is therefore derived from the NAME:

- The trailing country token ("BBC One UK", "ZDF DE", "ESPN USA") picks the region
  category, exactly like the cdnlive regions in gen_intl.py. Unknown countries fall
  through to genre classification rather than inventing a one-channel category.
- Genre classification (sports/kids/news/movies/...) applies to US-suffixed and
  country-agnostic names — the v1 category set, so dlhd rows land in the same
  categories the 93-channel US lineup already uses.
- The country suffix is STRIPPED for the EPG match name (epg.pw says "BBC One", not
  "BBC One UK") but kept in the display name.
- epg_cc is set to the real country; rows are only EPG-scanned when that code has a
  calibrated epg.pw file (the 9 in epg.EPG_COUNTRIES). Everything else shows honest
  "No Program Information" until more files are calibrated.
- Numbers run 1201+ (v2 ends at 1176), sequential over (category, name) — stable
  across rebuilds because classification is a pure function of the name. Stability
  is load-bearing: stream carry-over keys on the number.

Regenerate with:  python -m nmnowfeed.gen_dlhd <catalog.json> > nmnowfeed/dlhd_rows.py
"""

import json
import re
import sys

# trailing name token(s) -> (category, epg_cc)
REGION = [
    ("UK", "uk", "GB"), ("Ireland", "uk", "GB"),
    ("DE", "germany", "DE"), ("Germany", "germany", "DE"),
    ("France", "france", "FR"),
    ("Spain", "iberia", "ES"), ("Portugal", "iberia", "PT"), ("PT", "iberia", "PT"),
    ("Denmark", "nordics", "DK"), ("Norway", "nordics", "NO"), ("Sweden", "nordics", "SE"),
    ("Finland", "nordics", "FI"),
    ("NL", "benelux", "NL"), ("Netherland", "benelux", "NL"),
    ("Italy", "italy", "IT"),
    ("Poland", "cee", "PL"), ("CZ", "cee", "CZ"), ("SK", "cee", "SK"),
    ("Romania", "cee", "RO"), ("Bulgaria", "cee", "BG"), ("Serbia", "cee", "RS"),
    ("Croatia", "cee", "HR"), ("Hungary", "cee", "HU"),
    ("Greece", "greece", "GR"), ("Cyprus", "greece", "CY"),
    ("Russia", "russia", "RU"),
    ("Turkey", "turkey", "TR"), ("TR", "turkey", "TR"),
    ("Israel", "mideast", "IL"), ("UAE", "mideast", "AE"), ("Qatar", "mideast", "QA"),
    ("Arabic", "mideast", ""), ("MENA", "mideast", ""),
    ("MX", "latam", "MX"), ("Argentina", "latam", "AR"), ("Brasil", "latam", "BR"),
    ("Chile", "latam", "CL"), ("Columbia", "latam", "CO"), ("Colombia", "latam", "CO"),
    ("Uruguay", "latam", "UY"), ("Mexico", "latam", "MX"),
    ("CA", "canada", "CA"), ("Canada", "canada", "CA"),
    ("AU", "anz", "AU"), ("NZ", "anz", "NZ"),
    ("IN", "southasia", ""), ("PK", "southasia", ""), ("BD", "southasia", ""),
]

# genre rules, ordered; (regex, category) applied to the cleaned name
GENRE = [
    (r"18\+|player-\d+", "adult"),
    (r"big brother.*cam|quadview", "entertainment"),
    (r"cartoon|nick|disney|boomerang|cartoonito|teen\s*nick|universal kids|baby|kids|poptv|pop tv|minimax|dj ct", "kids"),
    (r"news|cnn|msnbc|c[- ]?span|newsnation|newsmax|headline|weather|bloomberg|cnbc|law ?& ?crime|court tv|al jazeera|cnews|lci|bfm", "news"),
    (r"discovery|nat ?geo|animal planet|history|smithsonian|science|american heroes|ahc|destination america|investigation|crime ?\+|oxygen|id\b", "documentary"),
    (r"hbo|cinemax|showtime|starz|mgm|epix|movie|tcm|film|encore|cinema", "premium"),
    (r"mtv|vh1|cmt|fuse|music|cmc\b", "music"),
    (r"espn|fox sports|fs1|fs2|bein|be ?in|dazn|sky sport|tnt sports|nfl|nba|nhl|mlb|golf|tennis|motor|racing|f1|motogp|sport|fight|msg\b|nesn|yes network|fanduel|spectrum|marquee|root sports|masn|sec network|acc network|big ten|pac-?12|espnu|redzone|willow|tyc|tudn|tdp|teledeporte|mundotoro|padel|cfp|space city|monumental|sportsnet", "sports"),
    (r"telemundo|uni ?mas|galavisi|universo|azteca|unicable|estrellas|las estrellas|canal ?5|deportes", "spanish"),
]

# categories appended after the v2 region set (order = rail order)
EXTRA_CATEGORIES = [
    ("africa", "Africa", "globe"),
    ("southasia", "South Asia", "globe"),
    ("adult", "18+", "lock"),
]

# channels that name an africa/south-asia/latam/canada identity without a suffix token
AFRICA_HINT = re.compile(r"supersport|dstv|m-?net|canal\+ .*afrique|canal\+ sport \d afrique", re.I)
SOUTHASIA_HINT = re.compile(r"star sports|ten sports|ptv sports|t sports|sony ten|willow", re.I)
LATAM_HINT = re.compile(r"globo|sportv|combate|azteca|win sports|vtv\+|record tv|futura|espn premium", re.I)
CANADA_HINT = re.compile(r"\btsn\d?\b|rds\b|ctv\b|noovo|ytv|citytv|cp24|cbc\b|global ca", re.I)

# Skip entirely: not channels (operator placeholders) — none known yet; the 18+
# players are kept under the adult category by explicit user intent ("all of them").


def classify(name: str) -> tuple[str, str, str]:
    """name -> (category, epg_cc, match_name)."""
    n = name.strip()
    # Big Brother cams & 18+ players first (their parens confuse suffix logic)
    for pat, cat in GENRE[:2]:
        if re.search(pat, n, re.I):
            return cat, "", n
    # trailing country token
    for tok, cat, cc in REGION:
        if n.lower().endswith(" " + tok.lower()):
            return cat, cc, n[: -(len(tok) + 1)].strip()
    if AFRICA_HINT.search(n):
        return "africa", "", n
    if SOUTHASIA_HINT.search(n):
        return "southasia", "", n
    if LATAM_HINT.search(n):
        return "latam", "BR" if re.search(r"globo|sportv|combate", n, re.I) else "", n
    if CANADA_HINT.search(n):
        return "canada", "CA", n
    cleaned = re.sub(r"\s+USA$", "", n).strip()
    for pat, cat in GENRE[2:]:
        if re.search(pat, cleaned, re.I):
            return cat, "US" if cat not in ("adult",) else "", cleaned
    return "entertainment", "US", cleaned


def short_label(display: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", display)
    for w in words:
        if len(w) >= 3:
            return w.lower()[:6]
    return (words[0] if words else "ch").lower()[:6]


def norm(n: str) -> str:
    n = re.sub(r"[^\w]+", " ", n.lower()).strip()
    return re.sub(r"\s+(hd|sd|fhd|uhd)$", "", n)


def build_rows(catalog: list[dict], base_norms: set[str]) -> tuple[list[tuple], dict[str, str]]:
    """Rows + {number: dlhd channel_id} from a LOADED catalog (build.py calls this
    every rebuild so NTV id/name changes can never rot the tier). base_norms are the
    cdnlive tier's names — a dlhd twin of an existing channel is skipped."""
    rows, ids = [], {}
    for c in catalog:
        if c["server"] != "dlhd":
            continue
        name = c["channel_name"]
        if norm(name) in base_norms:  # already served by the cdnlive tier
            continue
        cat_id, epg_cc, match_name = classify(name)
        number = str(1201 + len(rows))
        rows.append((match_name, number, name, short_label(name), cat_id, epg_cc, ""))
        ids[number] = c["channel_id"]
    return rows, ids


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    catalog_path = sys.argv[1] if len(sys.argv) > 1 else "C:/Users/Mayor/AppData/Local/Temp/ntv_catalog.json"
    catalog = json.load(open(catalog_path, encoding="utf-8"))["channels"]
    from .lineup import LINEUP, LINEUP_INTL  # cdnlive tier = the dedupe base

    existing = {norm(r[0]) for r in LINEUP + LINEUP_INTL}
    rows, ids = build_rows(catalog, existing)
    from collections import Counter
    print("rows: %d (dupe-skipped vs previous feed)" % len(rows), file=sys.stderr)
    for k, v in sorted(Counter(r[4] for r in rows).items()):
        print("  %-14s %d" % (k, v), file=sys.stderr)
    with open("nmnowfeed/dlhd_rows.py", "w", encoding="utf-8") as f:
        f.write('"""GENERATED by gen_dlhd.py — do not hand-edit; regenerate instead."""\n\n')
        f.write("LINEUP_DLHD = [\n")
        for r in rows:
            f.write("    %r,\n" % (r,))
        f.write("]\n\nDLHD_IDS = ")
        f.write(repr(ids))
        f.write("\n")
    print("wrote nmnowfeed/dlhd_rows.py", file=sys.stderr)
