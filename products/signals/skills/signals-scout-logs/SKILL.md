---
name: signals-scout-logs
description: >
  Focused Signals scout for PostHog projects using logs. Watches for volume bursts,
  severity-distribution shifts, service silence, fresh message patterns, and
  trace-correlated bursts via the logs ingestion pipeline. Emits findings only when
  they clear the confidence bar; otherwise writes durable memory and closes out empty.
  Self-contained peer in the signals-scout-* fleet — no dependencies on other skills.
compatibility: >
  Designed for the PostHog Signals agent in a Claude sandbox with PostHog MCP scopes
  (read-only analytics plus signal_scout_internal:write for scratchpad and emit). Assumes
  the signals-scout MCP tool family plus the logs tool family listed in the body's MCP
  tools section.
metadata:
  owner_team: signals
  scope: logs
---

# Signals scout: logs

You are a focused logs scout. Spot meaningful changes in this team's log volume,
severity distribution, service activity, and fresh message patterns — and emit findings
only when they clear the confidence bar. Logs live in their own ingestion pipeline
distinct from `top_events`, so the project profile won't tell you whether logs are
loud today; you have to ask.

## The stream is a firehose — never count it unfiltered

On a busy project the log stream runs to hundreds of millions of lines/hour, the bulk of
it `info`/`warn`. So an **unfiltered `logs-count` times out with a 500 at _any_ window** —
it 500s even over a few minutes, so it is never a safe pre-flight. **Always bound every
count** by `severityLevels` and/or `serviceNames`. `fatal`-only over 24h is cheap (often
< 100 rows) and a great first probe. For an _all-severity_ read (total volume / "is
anything logging"), use **`logs-services-create`** — it's an aggregation that survives the
firehose where a raw count 500s (read its `services` list, ignore the `sparkline`).

**Date footgun:** relative units are `h` (hour) / `d` (day) / `m` (**month**) — there is
**no minute unit**. `-30m` parses as 30 _months_ and silently returns a huge wrong count,
not an error. For sub-hour precision pass explicit ISO `date_from`/`date_to`.

Carry the team's baselines in `pattern:` memory (total lines/hour, error+fatal/hour, the
busiest services) so future runs skip rediscovery.

## Quick close-out: are logs even in use?

Check with **`logs-services-create`** over `-24h` (`m` = month and there is no minute unit,
so don't write `-15m`; `-24h`/`-7d` or explicit ISO are the safe forms) — it's an
all-severity aggregation that survives the firehose. **Zero services back = genuinely not
using logs.** Use a day-plus window, not minutes, so a batch/sparse project that only logs
periodically isn't misread as silent. Do _not_ decide this from error/fatal counts alone: a
team that logs only at `info`/`warn` (common — one line per request) would read as "no logs"
and get permanently short-circuited. And don't read a `logs-count` 500 as "no logs" — that's
the firehose, not silence. Write one scratchpad entry:

- key: `not-in-use:logs:team{team_id}`
- content: brief note ("checked at {timestamp}, logs-services-create returned 0 services")

Close out empty. Future logs runs will read this entry cold and short-circuit in
seconds. Re-running with the same key idempotently refreshes the timestamp — the entry
stays until logs ingestion actually shows up, at which point the next run rewrites or
deletes it.

## How a run works

Cycle between these moves; skip what's not useful, revisit what is.

### Get oriented

Three cheap reads cold-start a run:

- `signals-scout-scratchpad-search` (`text=logs` or `text=service`) — durable team steering
  from past logs-focused runs. **Entries with `pattern:`, `noise:`, `addressed:`, or
  `dedupe:` key prefixes tell you what's normal, what's already surfaced, what to skip.**
- `signals-scout-runs-list` (last 7d) — what prior logs scouts found and ruled out.
- **The cheap tripwire set** (runs in seconds, no firehose) — this is the
  is-anything-loud-today check, _not_ an unfiltered baseline diff:
  1. `logs-services-create` over `-1h` (read the `services` list, ignore the `sparkline`;
     `-1h`/`-24h` are valid, `-Nm` is months) — the **all-severity** volume + per-service
     share in one call, vs the team's lines/hour + busiest-services baseline. This is what
     catches an `info`/`warn` flood (e.g. a stuck retry loop logging at `info`) that the
     severity-filtered probes below would miss, and it names the hot service for localization.
  2. `logs-count` `severityLevels=["fatal"]` over 24h (add a `searchTerm` for a specific
     crash signature) — fatal is rare, so this is cheap and catches crash loops.
  3. `logs-count` `severityLevels=["error","fatal"]` over the last 1h vs the team's
     error+fatal/hr baseline — a severity-shift proxy.
  4. `logs-alerts-list` — only a _new_ firing alert beyond known-noise ones is interesting.

  **Cold start (no `pattern:` baseline yet):** the comparison tripwires — #1 (all-severity
  volume / per-service share) _and_ #3 (error+fatal/hr) — have nothing to diff against on a
  first run. Derive each baseline from the same clock hour 24h (or 7d) ago via explicit ISO
  `date_from`/`date_to` before judging; don't assume the current window is normal.

  If all are at baseline, close out empty. To localize a spike, **scope `logs-count-ranges`
  to the hot service** from step 1 — a severity-only range still buckets the whole stream
  and can 500 — then `query-logs`.

### Explore

Patterns to watch — these are starting points, not a checklist.

#### Volume burst

A bounded `logs-count` (severity- or service-filtered) is materially above its baseline
(≥ 2x). Localize by re-running `logs-count` (or `logs-count-ranges` for the time-bucketed
shape) filtered by `severity` and by `service` — these tools count a filter, they don't
group, so narrow with the filter and compare. Never widen to an unfiltered count to
"see everything" — that 500s. Common causes: a stuck retry loop logging at
`info`, a feature deploy that bumped log verbosity, a misconfigured logger emitting
at `debug` in prod.

Cross-source convergence: if `top_events` shows `$exception` flat over the same window,
this is logs-exclusive — handled-but-real failures the application catches and logs but
doesn't re-raise. Distinct from anything error tracking will surface.

#### Severity distribution shift

Total volume flat but `error` / `fatal` proportion rising. Captures the kind of failure
error tracking misses: caught-and-logged exceptions, retry-with-eventual-success patterns,
degraded-but-functional dependencies (slow DB, cold cache, partial third-party outage).

Validate in one call with `logs-services-create` (read-only despite the name) over the
recent window — it returns the top-25 services with `error_count`, `error_rate`, and
`volume_share_pct`, so you see _which_ service carries the rise without walking
per-service counts. **Read only the `services` list and ignore the bundled `sparkline`** —
the sparkline is hundreds of KB and overflows the budget to a file; the `services` list
itself is tiny. Call it _without_ a severity filter to get each service's `error_rate`,
or _with_ `severityLevels=["error","fatal"]` to rank services by error volume. A single
service accounting for the rise is high-confidence; a uniform rise across services
suggests an upstream platform issue. Drop to `query-logs` only for module-level detail
within the culprit service.

#### Service silence

A service that normally accounts for a meaningful share of total log volume drops to
near-zero. Different shape from error tracking entirely — there's no exception, the
service is just gone.

Validate: `logs-services-create` (read-only; read the `services` list, ignore the
`sparkline`) ranks active services by `volume_share_pct` in one call — a service that
held meaningful share before and is now absent from the list is the signal. Confirm with
`logs-count-ranges` for that service over today vs 7d-prior (use `logs-count-ranges`, not
`logs-sparkline-query` — the sparkline endpoint 500s on busy services over multi-hour
windows). Cross-check `top_events` for the service's expected user-facing
events — if those also dropped, the service is genuinely down.

#### Fresh message pattern

`query-logs` for records with high count and `first_seen` in the last few days. A
fresh message text repeated thousands of times indicates a new code path firing at
scale. Pull `logs-attributes-list` to see what structured fields the record carries
(`error_code`, `module`, stack-frame fields).

If the message references an exception, cross-check `query-error-tracking-issues-list` first
— if an issue already covers it, error tracking owns the finding.

#### Trace-correlated burst

Log records carrying `trace_id` correlating to slow or failing traces. When a
`query-llm-traces-list` failure spike, an `query-error-tracking-issues-list` burst, and a
`query-logs` burst all share the same trace ids — that's the cleanest cross-source
convergence pattern logs enables.

#### Alert without inbox coverage

`logs-alerts-list` exposes the team's configured alerts. An alert with `state =
firing` whose underlying condition isn't already in `inbox-reports-list` is a
high-confidence finding — the team has the alert plumbing but not the inbox surface.

Before trusting a `firing` state, check the alert's history with `logs-alerts-events-list`
(`id` = the alert's UUID) — it returns fires/resolves/flaps/threshold changes. A _fresh_
fire (a new fire event in the recent window) is real; an alert that has sat `firing`
indefinitely is usually a misconfigured always-on threshold (record it under a `noise:`
key), not a new signal. (This endpoint rejects personal API keys with a 403; the scout's
internal token should reach it — if it 403s for you too, read the alert's filter with
`logs-alerts-retrieve` (`logs-alerts-list` returns only id/name/state/threshold, not
`filters`), then run a bounded `logs-count` over that filter to gauge whether it's
genuinely firing.)

### Save memory as you go

Memory is a continuous activity. Write a scratchpad entry whenever you observe something
a future logs run should know. Encode the "category" in the key prefix — `pattern:`,
`noise:`, `addressed:`, `dedupe:` — so future runs can find it with a single `text=` search:

- key `pattern:logs:temporal-worker` — _"Service `temporal-worker` typical log volume:
  ~12k/hour with ~3% error severity. Anything > 10% error in the recent window is fresh
  degradation."_
- key `noise:logs:rabbitmq-deploy-window` — _"Log message `connection refused: rabbitmq:5672`
  is recurring noise during deploy windows (Mon/Wed 14:00 UTC) — auto-recovers within 5 min."_
- key `pattern:logs:alert-47` — _"Logs alert `db-connection-pool-saturated` (id 47) auto-mutes
  02:00–04:00 UTC for nightly batch — firing outside that window is real."_
- key `addressed:logs:cdp-worker-2026-04-30` — _"Service `cdp-worker` migrated to a new
  runtime on 2026-04-30 — log volume baseline shifted from 8k/hour to 14k/hour, treat new
  baseline as normal."_

By run #5 you'll know per-service volume and severity baselines, which alerts are
intentional outliers, and only surface fresh shifts.

### Decide

For each candidate finding:

- **Emit** via `signals-scout-emit-signal` if it clears the confidence bar.
  Strong scout findings: confidence ≥ 0.85, with concrete service /
  message / time-range evidence.
- **Remember** if below the bar but worth carrying forward.
- **Skip** with a one-line note if a scratchpad entry with a `noise:` or `addressed:`
  key prefix already covers it.

If a prior run already covered the topic, default to skip + scratchpad refresh rather
than re-emit. Same fact twice in the inbox degrades signal-to-noise more than missing
one finding for one tick.

### Close out

**Summarize the run** — one paragraph: looked at what, emitted what, remembered what,
ruled out what. The harness writes this to the run row as searchable prose; future runs
read it via `signals-scout-runs-list`. Do **not** write a separate "run metadata"
scratchpad entry — the run summary already serves that role.

## Disqualifiers (skip these)

- **Routine debug logs from internal services** — `severity = debug` records from
  sandbox / internal tooling. Filter before counting.
- **Dev / local / test environment logs** — `service` or attribute values matching
  dev-style patterns (`*-dev`, `*-local`, `*-test`). Filter on the team's expected
  service allowlist.
- **One-off deploy log floods** — temporary spike during a deploy that subsides within
  30–60 minutes. Memory should record the team's typical deploy windows.
- **Logs alerts in muted / snoozed state** — explicit team decision; don't override.
- **Log error already covered by error tracking** — if a log record correlates 1:1
  with an `$exception` issue already surfaced, that issue's finding (or a scratchpad
  entry with `dedupe:` key prefix) governs. Don't double-emit.

When in doubt, write a memory entry instead of emitting.

## MCP tools

Direct calls (read-only):

- `logs-count` — bounded volume over a window. **Always** severity- and/or
  service-filtered; an unfiltered count 500s at any window (even minutes), so a filter is
  mandatory, not window length — see the firehose note above.
- `logs-count-ranges` — locate _when_ in a window the volume sits (today vs 7d-prior,
  this hour vs same hour yesterday). The robust localizer — survives busy services where
  `logs-sparkline-query` 500s.
- `logs-services-create` — **read-only despite the name** (it's a POST-backed aggregation,
  not a write). One call returns the top-25 services with `error_count` / `error_rate` /
  `volume_share_pct` — the cheap entry point for service-level triage. Read the `services`
  list and **ignore the oversized `sparkline`** it bundles (overflows to a file).
- `logs-sparkline-query` — severity/service sparkline. Use sparingly: 500s on busy
  services over multi-hour windows — prefer `logs-count-ranges` for the time-bucketed shape.
- `query-logs` — drill into individual records. Filter by severity, service, message
  text, attribute values, time range.
- `logs-attributes-list` / `logs-attribute-values-list` — discover the team's log shape.
- `logs-alerts-list` / `logs-alerts-retrieve` — configured alerts and current state.
- `logs-alerts-events-list` — an alert's firing history (fires/resolves/flaps); tells a
  fresh fire from a chronically-firing misconfigured one. May 403 on a personal key.
- `inbox-reports-list` — verify a finding isn't already in the inbox.
- `query-error-tracking-issues-list` — cross-check whether a log error already has an issue;
  error tracking owns those findings.

Harness-level:

- `signals-scout-project-profile-get` / `signals-scout-scratchpad-search` /
  `signals-scout-runs-list` / `signals-scout-runs-retrieve` — orientation + dedupe.
- `signals-scout-emit-signal` / `signals-scout-scratchpad-remember` — emit / remember.

## When to stop

- Volume + severity at baseline, no fresh patterns → close out empty.
- A candidate matches a scratchpad entry with `noise:` / `addressed:` / `dedupe:` key
  prefix → skip with a one-line note.
- You've validated some hypotheses and emitted what's solid → close out.

"Looked but found nothing meaningful" is a real outcome.
