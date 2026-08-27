"""Regenerate the international half of lineup.py from NTV's catalog.

Run: python -m nmnowfeed.gen_intl <catalog.json>   (from https://ntv.cx/api/get-channels)

Emits the LINEUP_INTL literal block on stdout — paste it back into lineup.py under the
generated marker. Numbers are stable once pasted: rerunning prints a fresh numbering
for a fresh catalog, so treat a regen as a rename review, not a no-op. The curated US
block above the marker is never touched.

Region table and number bases are HERE, deliberately — a channel's number and its rail
category are the two things the viewer learns by heart; changing either is a UX break,
and both now have one obvious place to be read.

The 2026-08-23 epg.pw country set (US GB DE FR AU NZ BR CA RU) decides who gets a
schedule (epg.EPG_COUNTRIES); every other country publishes with streams and honest
"No Program Information" rows until epg.pw grows a file for it.
"""

import json
import re
import sys

# (category_id, label, icon, [(country_code, number_base), ...]) — bases leave gaps
# for insertions and never collide with the US block (101-705).
REGIONS = [
    ("uk", "UK", "uk", [("gb", 801)]),
    ("germany", "Germany & Austria", "germany", [("de", 841), ("at", 871)]),
    ("france", "France", "france", [("fr", 881)]),
    ("iberia", "Spain & Portugal", "iberia", [("pt", 911), ("es", 931)]),
    ("nordics", "Nordics", "nordics", [("dk", 951), ("se", 963)]),
    ("benelux", "Benelux", "benelux", [("nl", 973), ("be", 983)]),
    ("italy", "Italy", "italy", [("it", 985)]),
    ("cee", "Central & Eastern Europe", "cee", [("pl", 991), ("cz", 1011), ("bg", 1015), ("ro", 1029)]),
    ("greece", "Greece & Cyprus", "greece", [("gr", 1037), ("cy", 1049)]),
    ("russia", "Russia", "russia", [("ru", 1057)]),
    ("turkey", "Turkey", "turkey", [("tr", 1063)]),
    ("latam", "Latin America", "latam", [("br", 1071), ("ar", 1085), ("mx", 1091), ("cl", 1097), ("uy", 1099)]),
    ("canada", "Canada", "canada", [("ca", 1101)]),
    ("anz", "Australia & NZ", "anz", [("au", 1117), ("nz", 1143)]),
    ("mideast", "Middle East", "mideast", [("ae", 1155), ("sa", 1159), ("il", 1167)]),
]


def _short(name: str) -> str:
    tok = re.sub(r"[^0-9a-zA-Z]+", " ", name).strip().split()
    s = (tok[0].lower() if tok else "ch")[:4]
    return s or "ch"


def main() -> int:
    catalog = json.load(open(sys.argv[1], encoding="utf-8"))["channels"]
    titan = {}
    for c in catalog:
        if c["server"] == "cdnlive":
            titan.setdefault(c["channel_code"], []).append(c)

    lines = []
    for cat_id, label, icon, ccs in REGIONS:
        lines.append('    # --- %s ---' % label)
        for cc, base in ccs:
            for c in sorted(titan.get(cc, []), key=lambda c: c["channel_name"]):
                n = c["channel_name"]
                # epg_cc is ALWAYS the catalog country (upper) — it is also the stream
                # lookup key. Whether epg.pw has a file for it is decided by
                # epg.EPG_COUNTRIES membership, never by blanking this column.
                lines.append('    ("%s", "%d", "%s", "%s", "%s", "%s", ""),'
                             % (n, base, n.replace('"', "'"), _short(n), cat_id, cc.upper()))
                base += 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
