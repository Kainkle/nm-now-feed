# The feed-build trigger — and why it moved off GitHub's cron

**2026-08-30:** GitHub's scheduler dropped eight consecutive feed-build slots
(02:37–05:21 UTC) with the workflow "active" and the status page green. The build
pipeline itself is fixed (tarpit breaker + CI poison refs + race-healed push — see
git history), but the *trigger* needed an owner that reports failures. Chosen:
an external cron service pinging `repository_dispatch` (workflow v3.5, `feed-tick`).

The freshness guard makes every tick a no-op when the published feed is under 25
minutes old — the tick only has to ARRIVE, not be smart. GitHub's own cron stays
enabled as a free second trigger; redundant triggers cannot stack.

## Setup (one time, ~2 minutes, both steps are yours — token and account)

### 1. The token (GitHub)

1. github.com → Settings → Developer settings → **Fine-grained tokens** → Generate.
2. Repository access: **Only select repositories** → `Kainkle/nm-now-feed`.
3. Permissions → Repository permissions → **Contents: Read and write**.
   (That is all `repository_dispatch` needs — nothing else.)
4. Copy the token. If it ever leaks, revoke it from this same page; the blast
   radius is push-access to this one feed repo.

### 2. The ping (cron-job.org — free tier carries custom headers)

1. Create the account → **Create Cronjob**.
2. URL: `https://api.github.com/repos/Kainkle/nm-now-feed/dispatches`
3. Method: `POST`
4. Advanced → Headers:
   - `Authorization: Bearer <PASTE THE TOKEN>`
   - `Accept: application/vnd.github+json`
   - `Content-Type: application/json`
5. Body: `{"event_type":"feed-tick"}`
6. Schedule: every **20 minutes**.
7. **Enable failure notifications** — that doubles as the dead-trigger alarm
   (the one alarm GitHub never gave us).

## Operating notes

- A healthy tick logs `published feed age: XXm` then either `feed is fresh —
  skipping this slot` (guard) or a full build + bot commit.
- Manual build NOW: `gh workflow run build-feed --repo Kainkle/nm-now-feed
  --ref main -f force=true` (force bypasses the guard).
- Boxes self-heal per-channel regardless: every stream ref carries
  resolver+channel_id, and the app's ladder re-mints on tune.
