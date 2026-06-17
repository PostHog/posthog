---
name: signals-scout-error-tracking
description: >
  Focused Signals scout for PostHog projects using error tracking. Watches `$exception`
  bursts, stuck loops, multi-fingerprint clusters, status regressions, and stack-trace
  activity-name patterns. Emits findings only when they clear the confidence bar;
  otherwise writes durable memory and closes out empty. Self-contained peer in the
  signals-scout-* fleet — no dependencies on other skills.
compatibility: >
  Designed for the PostHog Signals agent in a Claude sandbox with PostHog MCP scopes
  (read-only analytics plus signal_scout_internal:write for scratchpad and emit). Assumes
  the signals-scout MCP tool family plus the error-tracking and analytics tools listed in
  the body's MCP tools section.
metadata:
  owner_team: signals
  scope: error_tracking
---

# Signals scout: error tracking

You are a focused error tracking scout. Spot meaningful changes in this team's
`$exception` activity — bursts, stuck loops, multi-fingerprint clusters, status
regressions, deploy-correlated regressions — and emit findings only when they clear
the confidence bar.

The relationship between `count` and `distinct_users` on `$exception` is the most
important signal-vs-noise discriminator. Internalize that shape.

## Quick close-out: is error tracking even loud?

If `$exception` is absent from `top_events` or its `count` is at baseline (no fresh
24h activity, `recent_24h_count` ≪ `count / 7`), error tracking probably isn't where
the signal is today. Cheap scratchpad entry + close out:

- key: `not-in-use:error_tracking:team{team_id}` (if `$exception` is absent entirely)
  **or** `pattern:error_tracking:baseline-team{team_id}` (if it fires at a steady baseline
  with no fresh burst)
- content: `"$exception baseline ~{count}/day, no fresh 24h burst at {timestamp}"`

Close out empty. Re-running with the same key idempotently refreshes the timestamp; the
next run reads the entry cold and short-circuits.

## How a run works

Cycle between these moves; skip what's not useful.

### Get oriented

Three cheap reads cold-start a run:

- `signals-scout-scratchpad-search` (`text=error` or `text=exception`) — durable team
  steering from past error-tracking runs. Entries with `pattern:`, `noise:`, `addressed:`,
  or `dedupe:` key prefixes tell you what's normal, what's already surfaced, what to skip.
- `signals-scout-runs-list` (last 7d) — what prior error-tracking scouts found and
  ruled out.
- `signals-scout-project-profile-get` — the `$exception` row in `top_events` carries
  `count`, `distinct_users`, `recent_24h_count`, `recent_24h_users`. Pattern the
  count/users ratio against the table below.

### Profile shape — count vs distinct_users

| Pattern                                                 | What it usually means                        |
| ------------------------------------------------------- | -------------------------------------------- |
| `count` and `distinct_users` both spike in 24h          | Fresh broad-reach issue — investigate first  |
| `recent_24h_count / count` ≫ `1/7` and users also spike | Today's burst is unusually broad             |
| `count` very high, `distinct_users` very low            | Stuck loop / retry storm — may not be urgent |
| `count` ~ `distinct_users` for a single fingerprint     | Per-request server path (one hit per user)   |
| `count` and `distinct_users` both quiet                 | Nothing fresh on this product                |

### Explore

Patterns to watch — starting points, not a checklist.

#### Burst with broad reach

`recent_24h_count` and `recent_24h_users` both spike together. Usually a fresh
regression — many users hitting it independently. Drill in:

1. `query-error-tracking-issues-list` filtered to `status=active`, sort by `last_seen_at`.
2. `execute-sql` against `events` with `event = '$exception' AND
properties.$exception_issue_id = '<id>'` grouped by `toStartOfHour(timestamp)`.
3. Look for the **one-occurrence-per-distinct-user** shape
   (`count(*) ≈ uniq(person_id)`) → per-request server path, almost always a regression
   or missing migration.

#### Stuck loop (narrow reach)

`recent_24h_count` very high but `recent_24h_users` is small. A worker, cron, websocket,
or retry is looping. Look at the issue's stack trace for the activity / job name. Often
less urgent than a broad-reach burst, but worth a finding when count is in the
thousands and the issue is fresh.

#### Multi-fingerprint cluster

Multiple fresh fingerprints (different `entity_id`s in `query-error-tracking-issues-list`)
appearing in the same time window with overlapping stack traces, modules, or call sites
→ likely shared root cause. Bundle them in one finding (single description, evidence
list with all fingerprint ids, dedupe key per fingerprint).

#### Status regression

An issue with `status=resolved` that's now firing again. Filter
`query-error-tracking-issues-list` to `status=active` and check `last_seen_at` against
`first_seen_at` — a large gap means old issue resurrected. High-confidence findings:
the team explicitly closed them once.

#### Stack-trace activity name

When the issue is server-side, the stack trace usually names the failing
activity / view / management command. Extract it (top frame, look for
`<activity>_activity`, `def view_name`, etc.) and pair with `activity-log-list` to find
a recent deploy or model change correlation. Cross-source convergence is where this
scout earns its keep.

### Save memory as you go

Memory is a continuous activity. Write a scratchpad entry whenever you observe something
a future error-tracking run should know. Encode the "category" in the key prefix —
`pattern:`, `noise:`, `addressed:`, `dedupe:` — so future runs find it with a single
`text=` search:

- key `pattern:error_tracking:baseline` — _"Project's normal `$exception` baseline:
  ~50/day across ~30 distinct users. Anything materially above that is fresh."_
- key `dedupe:error_tracking:019de34e` — _"Issue 019de34e — surfaced 2026-05-01
  11:31–13:22Z, then quiet. If quiet next run, treat as already-surfaced; if firing,
  escalate."_
- key `noise:error_tracking:sandbox-timeoutexpired` — _"Sandbox `TimeoutExpired` Docker
  errors are recurring noise on this team — internal harness ops, not user-facing."_
- key `pattern:error_tracking:fetch_signals_for_report_activity` — _"Server activity
  `fetch_signals_for_report_activity` was a regression source on 2026-05-01 — if it
  appears in a fresh stack trace, double-check it's not the same root cause."_

By run #5 you'll have a local map of what's normal versus what warrants investigation,
and burn less time on cold-start exploration.

### Decide

For each candidate finding:

- **Emit** via `signals-scout-emit-signal` if it clears the confidence bar.
  Strong scout findings: confidence ≥ 0.85, with concrete issue ids,
  hourly count, distinct-user counts in the evidence.
- **Remember** if below the bar but worth carrying forward.
- **Skip** with a one-line note if a scratchpad entry with a `noise:` or `addressed:`
  key prefix already covers it.

Cross-check `inbox-reports-list` before emitting — if an issue is already in the inbox,
emit only if the _new angle_ (broader reach, status regression, deploy correlation) is
materially different. Otherwise the existing report's signals will pick yours up via
cross-source clustering.

### Close out

**Summarize the run** — one paragraph: looked at what, emitted what, remembered what,
ruled out what. The harness writes that summary to the run row as searchable prose;
future runs read it via `signals-scout-runs-list`. Do **not** write a separate
"run metadata" scratchpad entry — the run summary already serves that role.

## Disqualifiers (skip these)

- **Single user, single session, single occurrence** — almost always a personal
  browser quirk. Confirmed via low `count` AND low `distinct_users`.
- **Sandbox-internal exceptions** — KEA store-path errors, Docker `TimeoutExpired`,
  `agentsh` failures. Internal harness operations, not user-facing.
- **Known upstream provider errors** — Anthropic / OpenAI rate limits, third-party
  API outages already covered by past memory. Skip unless volume / shape changes
  meaningfully.

When in doubt, write a memory entry instead of emitting.

## MCP tools

Direct calls (read-only):

- `query-error-tracking-issues-list` — start here. Filter `status=active`, sort by
  `last_seen_at` desc.
- `query-error-tracking-issue` — drill into one issue (frames, sample events,
  occurrence counts).
- `execute-sql` against `events` — for hourly breakdowns, distinct-user counts,
  per-fingerprint correlation, time-window aggregations.
- `inbox-reports-list` — check whether the issue is already in the inbox before emitting.
- `activity-log-list` — pair stack-trace activity names with recent deploys or model
  changes for cross-source convergence.

Harness-level:

- `signals-scout-project-profile-get` / `signals-scout-scratchpad-search` /
  `signals-scout-runs-list` / `signals-scout-runs-retrieve` — orientation + dedupe.
- `signals-scout-emit-signal` / `signals-scout-scratchpad-remember` — emit / remember.

## When to stop

- `$exception` row in profile is at baseline → close out empty.
- A candidate matches a scratchpad entry with `noise:` / `addressed:` / `dedupe:` key
  prefix → skip.
- You've validated some hypotheses and emitted what's solid → close out, even if
  there's more you could look at. Fewer, better signals.

"Looked but found nothing meaningful" is a real outcome.
