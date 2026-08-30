# The feed-build trigger (2026-08-30) — a self-arming GitHub worker

**No user setup. No user keys. No user machines.** The user asked for an
always-on trigger that scales to any number of boxes and needs nothing from
him. This is it.

## Why it exists

GitHub's own cron dropped eight consecutive build slots (02:37–05:21 UTC) and
later a four-hour stretch, with the workflow "active" and the status page
green. Best-effort timers cannot be the only heartbeat for a feed that boxes
poll every 5 minutes.

## How it works

Two workflows, one chain:

1. **`feed-ticker.yml`** — the worker. Each run sleeps 19 minutes, then POSTs
   TWO `repository_dispatch` events with the run-scoped `GITHUB_TOKEN`
   (a token GitHub makes inside the run; it is dead when the run ends):
   - `feed-tick` → triggers the build.
   - `tick-chain` → starts the next ticker run. The chain arms itself.
2. **`build-feed.yml`** — the builder. Fires on `feed-tick`. Its freshness
   guard skips the build when the published feed is under 25 minutes old, so
   redundant triggers cannot stack work.

The normally-fatal rule — "events made with GITHUB_TOKEN start no workflows" —
has one documented exception: `repository_dispatch`. The chain rides exactly
that exception. Proven live 2026-08-30: gen 1 `33316469507` armed gen 2
`33316521805`, and gen 1's `feed-tick` produced guard-skipped build
`33316521622` (13 s, success).

## Safety rails

- `concurrency: feed-ticker / cancel-in-progress: true` — exactly one ticker
  alive. A re-seed cancels the sleeping run (it has dispatched nothing) and
  carries the chain itself. A second chain cannot fork off the first.
- Cron `3,33 * * * *` on the ticker is a RE-SEED only: if a link fails, a new
  chain starts within 30 minutes.
- The build's own cron (`7,21,37,51`) stays as a free extra trigger; the
  guard dedupes everything.
- A link that gets a non-204 from either dispatch FAILS loudly (visible in
  `gh run list --workflow feed-ticker.yml`).

## Scale

The feed is one file; every box polls the same URL. The number of boxes adds
no work to the trigger or the build. Per-box stream healing is the app's
recipe ladder (every stream ref carries `resolver` + `channel_id`), already
in production.

## Operating notes

- Chain health: `gh run list --repo Kainkle/nm-now-feed --workflow feed-ticker.yml`
  — consecutive `success` runs = alive. A gap longer than ~35 min = dead chain;
  the re-seed timer restarts it, or seed by hand:
  `gh api -X POST repos/Kainkle/nm-now-feed/dispatches -f event_type=tick-chain`
- Build NOW: `gh workflow run build-feed --repo Kainkle/nm-now-feed --ref main -f force=true`
- To change the cadence: edit `GAP_S` in `feed-ticker.yml` (seconds). The next
  generation picks it up.
