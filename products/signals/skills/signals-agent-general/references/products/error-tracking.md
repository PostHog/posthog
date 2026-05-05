# Lens: error tracking

The project profile's `top_events` will surface `$exception` if it's loud — and
the per-event `count`, `distinct_users`, `recent_24h_count`, `recent_24h_users`
fields tell you the **shape** of the volume. The relationship between count and
distinct_users is the most important signal-vs-noise discriminator on this
product.

## Quick scan from the profile alone

Look at the `$exception` row in `top_events`:

| Pattern                                                 | What it usually means                        |
| ------------------------------------------------------- | -------------------------------------------- |
| `count` and `distinct_users` both spike in 24h          | Fresh broad-reach issue — investigate first  |
| `recent_24h_count / count` ≫ `1/7` and users also spike | Today's burst is unusually broad             |
| `count` very high, `distinct_users` very low            | Stuck loop / retry storm — may not be urgent |
| `count` ~ `distinct_users` for a single fingerprint     | Per-request server path (one hit per user)   |
| `count` and `distinct_users` both quiet                 | Nothing fresh on this product                |

If nothing in the profile is loud, error tracking is probably not where the
signal is today. Move on.

## Patterns to look for

### Burst with broad reach

`recent_24h_count` and `recent_24h_users` both spike together. Usually a fresh
regression — many users hitting it independently. Drill in:

1. `error-tracking-issues-list` filtered to `status=active`, sort by
   `last_seen_at`.
2. `execute-sql` against `events` with
   `event = '$exception' AND properties.$exception_issue_id = '<id>'` grouped
   by `toStartOfHour(timestamp)` to see the burst window.
3. Look for the **one-occurrence-per-distinct-user** shape (`count(*) ≈
uniq(person_id)`) → per-request server path, almost always a regression /
   missing migration.

The 2026-05-01 access-control finding (see
[`../finding-schema.md`](../finding-schema.md) worked example) is the canonical
shape: 434 occurrences across 434 distinct users in two hours, then quiet.

### Stuck loop (narrow reach)

`recent_24h_count` very high but `recent_24h_users` is small. A worker, cron,
websocket, or retry is looping. Look at the issue's stack trace for the activity
/ job name. Often less urgent than a broad-reach burst, but worth a finding when
count is in the thousands and the issue is fresh.

### Multi-fingerprint cluster

Multiple fresh fingerprints (different `entity_id`s in
`error-tracking-issues-list`) appearing in the same time window with overlapping
stack traces, modules, or call sites → likely shared root cause. Bundle them in
one finding (single description, evidence list with all fingerprint ids, dedupe
key per fingerprint).

### Status regression

An issue with `status=resolved` that's now firing again. Filter
`error-tracking-issues-list` to `status=active` and check `last_seen_at` against
`first_seen_at` — large gap = old issue resurrected. High-confidence findings:
the team explicitly closed them once.

### Stack-trace activity name

When the issue is server-side, the stack trace usually names the failing
activity / view / management command. Extract it (top frame, look for
`<activity>_activity`, `def view_name`, etc.) and pair with `activity-log-list`
to find a recent deploy or model change correlation. Cross-source convergence is
where this scout earns its keep.

## Disqualifiers (skip these)

- **Single user, single session, single occurrence** — almost always a personal
  browser quirk. Confirmed via low `count` AND low `distinct_users`.
- **Dev / local environment** — `properties.environment ∈ {dev, local, test}` or
  the user is internal. Filter before weighing.
- **Sandbox-internal exceptions** — KEA store-path errors, Docker
  `TimeoutExpired`, `agentsh` failures. Internal harness operations, not
  user-facing.
- **Known upstream provider errors** — Anthropic / OpenAI rate limits, third-party
  API outages already covered by past memory. Skip unless volume / shape changes
  meaningfully.

When in doubt, write a memory entry instead of emitting.

## MCP tools

- `error-tracking-issues-list` — start here. Filter `status=active`, sort by
  `last_seen_at` desc.
- `error-tracking-issues-retrieve` — drill into one issue (frames, sample
  events, occurrence counts).
- `execute-sql` against `events` — for hourly breakdowns, distinct-user counts,
  per-fingerprint correlation, time-window aggregations.
- `inbox-reports-list` — check whether the issue is already in the inbox before
  emitting; pre-existing inbox coverage is a strong skip signal.
- `activity-log-list` — pair stack-trace activity names with recent deploys or
  model changes for cross-source convergence.

## Memory shapes worth writing

After investigating error tracking on a project, leave durable steers like:

- _"Project's normal `$exception` baseline: ~50/day across ~30 distinct users.
  Anything materially above that is fresh."_ (`pattern`, `domain:error_tracking`)
- _"Issue 019de34e — surfaced 2026-05-01 11:31-13:22Z, then quiet. If quiet next
  run, treat as already-surfaced; if firing, escalate."_ (`dedupe`,
  `entity:019de34e`)
- _"Sandbox `TimeoutExpired` Docker errors are recurring noise on this team —
  internal harness ops, not user-facing."_ (`noise`, `domain:error_tracking`)
- _"Server activity `fetch_signals_for_report_activity` was a regression source
  on 2026-05-01 — if it appears in a fresh stack trace, double-check it's not
  the same root cause."_ (`pattern`, `domain:error_tracking`,
  `entity:fetch_signals_for_report_activity`)

These compound: by run #5, the scout has a local map of what's normal versus what
warrants investigation, and burns less time on cold-start exploration.
