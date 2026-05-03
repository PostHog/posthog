# Lens: logs

Logs don't show up in the project profile's `top_events` — they live in a
separate ingestion pipeline with their own severity / service / attribute
taxonomy. The profile won't tell you whether logs are loud today; you have to
ask. `logs-count` over the recent window is the cheap entry point. The
relationship between **severity distribution** and **service** is the primary
signal-vs-noise discriminator.

## Quick scan via cheap reads

The profile is silent on logs, so cold-start with `logs-count` (total volume in
the recent window) and `logs-count-ranges` (today vs 7d-prior baseline,
optionally broken down by `severity`):

| Pattern                                                                  | What it usually means                            |
| ------------------------------------------------------------------------ | ------------------------------------------------ |
| Total volume in 24h ≫ 7d-prior baseline (≥ 2x)                           | Stuck retry / log-level misconfig / new deploy   |
| Total volume collapsed (≥ 50% drop) without a corresponding traffic drop | Service silent — outage or instrumentation gap   |
| `error` / `fatal` ratio rising while total volume flat                   | Handled failures climbing — partial degradation  |
| `error` / `fatal` concentrated to one `service` / `source`               | Service-specific regression                      |
| New message text with high count and recent `first_seen`                 | Fresh code path or new error pattern             |
| `logs-alerts-list` shows an alert firing                                 | Already actionable — verify inbox coverage first |

If volume is at baseline and severity distribution is unremarkable, logs are
probably not where the signal is today. Move on.

## Patterns to look for

### Volume burst

`logs-count` over 24h is materially above the 7d-prior baseline. Drill in with
`logs-count-ranges` broken down by `severity` and `service` to localize. Common
causes: a stuck retry loop logging at `info`, a feature deploy that bumped log
verbosity, or a misconfigured logger emitting at `debug` in prod.

Cross-source convergence: if `top_events` shows `$exception` flat over the
same window, this is logs-exclusive (handled-but-real failures the application
catches and logs but doesn't re-raise) — distinct from anything error tracking
will surface.

### Severity distribution shift

Total volume flat, but `error` / `fatal` proportion rising. Captures the kind
of failure error tracking misses: caught-and-logged exceptions, retry-with-
eventual-success patterns, degraded-but-functional dependencies (slow DB,
cold cache, partial third-party outage).

Validate via `query-logs` filtered to `severity ∈ {error, fatal}` over the
recent window, grouped by `service` or `module`. A single service accounting
for the rise is high-confidence; a uniform rise across services suggests an
upstream platform issue.

### Service silence

A service that normally accounts for a meaningful share of total log volume
drops to near-zero. Different shape from error tracking entirely — there's
no exception, the service is just gone. Validate:

1. `logs-attribute-values-list` on `service` to enumerate active services.
2. `logs-count-ranges` per service over today vs 7d-prior to confirm the
   missing service was active before.
3. Cross-check `top_events` and `query-trends` for the service's expected
   user-facing events — if those also dropped, the service is genuinely down.

### Fresh message pattern

`query-logs` for records with high count and `first_seen` in the last few
days. A fresh message text repeated thousands of times indicates a new code
path firing at scale. Pull `logs-attributes-list` to see what structured
fields the record carries — `error_code`, `module`, or stack-frame fields
help localize even without the source.

If the message references an exception, cross-check
`error-tracking-issues-list` first — if an issue already covers it, error
tracking owns the finding.

### Trace-correlated burst

Log records carrying `trace_id` correlating to slow or failing traces. The
scout can see this when a `query-llm-traces-list` failure spike, an
`error-tracking-issues-list` burst, and a `query-logs` burst all share the
same trace ids. That's the cleanest cross-source convergence pattern logs
enables.

### Alert without inbox coverage

`logs-alerts-list` exposes the team's configured alerts. An alert with
`state ∈ {firing, triggered}` whose underlying condition isn't already in
`inbox-reports-list` is a high-confidence finding — the team has the alert
plumbing but not the inbox surface.

## Disqualifiers (skip these)

- **Routine debug logs from internal services** — `severity = debug` records
  from sandbox / internal tooling. Filter before counting.
- **Dev / local / test environment logs** — `service` or attribute values
  matching dev-style patterns (`*-dev`, `*-local`, `*-test`). Filter on the
  team's expected service allowlist.
- **One-off deploy log floods** — temporary spike during a deploy that
  subsides within 30-60 minutes. Memory should record the team's typical
  deploy windows.
- **Logs alerts in muted / snoozed state** — explicit team decision; don't
  override.
- **Log error already covered by error tracking** — if a log record
  correlates 1:1 with an `$exception` issue already surfaced, that issue's
  finding (or a memory entry tagged `dedupe`) governs. Don't double-emit.

When in doubt, write a memory entry instead of emitting.

## MCP tools

- `logs-count` — start here. Total volume over the recent window.
- `logs-count-ranges` — compare windows (today vs 7d-prior, this hour vs
  same hour yesterday); supports breakdowns.
- `logs-sparkline-query` — sparkline shape over a window; useful for spotting
  a sharp burst vs a sustained shift.
- `query-logs` — drill into individual records. Filter by severity, service,
  message text, attribute values, time range.
- `logs-attributes-list` — what attribute fields exist on log records.
- `logs-attribute-values-list` — values for an attribute (e.g. all `service`
  values active in the recent window).
- `logs-alerts-list` / `logs-alerts-retrieve` — team's configured alerts and
  their current state.
- `inbox-reports-list` — verify a finding isn't already in the inbox before
  emitting.
- `error-tracking-issues-list` — cross-check whether a log error already has
  an issue; error tracking owns those findings.

## Memory shapes worth writing

After investigating logs on a project, leave durable steers like:

- _"Service `temporal-worker` typical log volume: ~12k/hour with ~3% error
  severity. Anything > 10% error in the recent window is fresh degradation."_
  (`pattern`, `domain:logs`, `entity:temporal-worker`)
- _"Log message `connection refused: rabbitmq:5672` is recurring noise during
  deploy windows (Mon/Wed 14:00 UTC) — auto-recovers within 5 min."_
  (`noise`, `domain:logs`)
- _"Logs alert `db-connection-pool-saturated` (id 47) auto-mutes 02:00-04:00
  UTC for nightly batch — firing outside that window is real."_ (`pattern`,
  `domain:logs`, `entity:alert-47`)
- _"Service `cdp-worker` migrated to a new runtime on 2026-04-30 — log volume
  baseline shifted from 8k/hour to 14k/hour, treat new baseline as normal."_
  (`addressed`, `domain:logs`, `entity:cdp-worker`)

These compound: by run #5, the scout has the team's per-service volume and
severity baselines, knows which alerts are intentional outliers, and only
surfaces fresh shifts.
