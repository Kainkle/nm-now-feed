# Source recipes — the registry spec (v1)

_One recipe per source. A recipe is pure data that describes how to turn a content id
into a playable URL + headers. The runner (embedded in each app) executes it. A source
changing shape becomes a recipe version bump — boxes heal on their next poll, no app
rebuild, for every app at once._

**Why this exists (measured 2026-08-27/28):** dlhd reorged their whole TV tier overnight
— every stream page died and the id space rotated. The repair cost a same-day re-reverse
plus an app release (PhoenixResolver port) plus a bench cycle. With recipes, that event
is one commit to this directory.

## Registry mechanics (v1 — deliberately no server)

- `index.json` — the ONE url apps poll: per-source `{source_id, version, status, engine,
  last_verified}`. Apps fetch a full recipe only when its version changes.
- `{source_id}.json` — the recipe itself.
- **Git history is the version log.** When a source breaks, `git log -- {source_id}.json`
  is the diff of what changed.
- **Write access = git push to this repo** (the sourcing pipeline / the agent). Apps only
  read. Served as raw JSON over HTTP — the exact deployment pattern the feed already
  proved (apps poll it every 5 min today).
- Raw-URL CDN staleness is ~5 min; acceptable for recipe distribution (a broken source
  already means the compiled fallback carried in the app). v2 can front this with the
  edge proxy for instant propagation + ETag caching.

## Recipe shape

```json
{
  "source_id": "phoenix_dlhd",
  "version": 1,
  "status": "working",
  "last_verified": "2026-08-28T00:00:00Z",
  "engine": "http",
  "content_key": "channel_id",
  "steps": [ ... ],
  "output": { "url": "$master", "headers": { "Referer": {"origin_of": "$daddy"}, "User-Agent": "$ua" } },
  "token_behavior": { "expires_seconds": 10800, "bound_to": "minter_ip", "mint_on": "player_error" },
  "known_child_domains": ["dlhd.st", "dlstreams.st", "*.romponalis.st"],
  "escape_hatch": false,
  "notes": "free prose: the traps, in priority order"
}
```

- `status`: `working` | `degraded` | `broken` | `unverified`. The health-check job owns
  this field; the runner refuses `broken` recipes (falls back to the compiled chain).
- `engine`: `http` (pure HTTP + regex — cheapest, no JS execution), `stage` (the QuickJS
  world executes the site's own JS on-box — for JS-gated sources), `webview` (emergency
  escape only; the fleet direction is WebView-free).
- `content_key`: what per-item input the recipe consumes (`channel_id` today — the
  StreamRef carries it alongside `resolver`).
- `escape_hatch`: when a source truly cannot be expressed in steps, the recipe names a
  compiled handler instead of contorting the schema. Rare by design.

## The http-engine verbs (v1 — exactly what the runner implements)

Values may reference captures by `$name`. Runner builtins: `$ua` (the Chrome desktop
identity), `$content_id` (the item's content key). URL templates interpolate
`{content_id}`.

| verb | fields | meaning |
|---|---|---|
| `fetch` | `url`, `referer?`, `ua?`, `save`, `extract?` | HTTP GET a page; save body; run extracts over it |
| `extract` | `from`, `extract` | run extracts over a previously saved string |
| `decode_base64` | `from`, `save`, `variant: std\|urlsafe` | decode one captured string |
| `decode_join` | `from`, `lookup`, `save`, `variant` | concat(decoded(lookup[p]) for p in list) — reassembly chains |
| `rewrite` | `from`, `find`, `replace`, `save` | string rewrite (host swaps) |
| `verify` | `url`, `referer?`, `expect_first_line\|expect_regex` | final proof the mint is playable; failure = recipe failure |

Extract entries: `{name, regex, multi?, pair?, template?, filter_contains?}` —
- `multi`: all matches (list) instead of first
- `pair`: two captures → a map (group 1 → group 2)
- `template`: `{name}` placeholders in the regex interpolate saved values first
  (titan's decoder function name is RANDOMIZED per page load — the regex must be built
  from a prior capture, never hardcoded)
- `filter_contains`: with `multi`, first match whose value contains this substring

`referer` (and any header value) may be: a literal, `$capture`, or
`{"origin_of": "$capture"}` — the origin (scheme://host) of a captured URL. Phoenix's
output Referer is the daddy shard's origin, and the shard rotates: it must be derived,
never written down.

## The stage-engine verbs (v2 — the runner's second engine)

For JS-gated sources the verbs are the descriptor the stage already consumes (proven in
playerlab phases 1–3): `entry` (world mount URL template), `worldExtras`, `candidateHosts`
(the hunter's accept list), `tierPreference` (the router's ladder), plus the same
`output` header rules. The stage executes the site's own JS on-box — which satisfies
IP-locked tokens exactly like the http engine, but for sources that need code, not just
pages. Authored when the stage seam lands; the schema reserves the fields above.

## Authoring law

A recipe is only as good as its worst trap. Every known trap goes in `notes` in priority
order, and — where the schema can express it — becomes a step that DEFENDS against it
(the verify step, template regexes, origin-derived referers). The two recipes in this
directory were translated line-for-line from the proven Python resolvers (`phoenix.py`,
`titan.py` in the feed builder) — those files remain the reference until the runner has
eaten both families for a full source cycle.
