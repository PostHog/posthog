---
name: authoring-log-alerts
description: >
  Author useful, low-noise log alerts on services in a PostHog project. Use when the user asks to set up
  alerts for their logs, suggest alerts they should add, or evaluate whether a service is worth monitoring.
  Covers service triage, baseline characterisation, threshold drafting, back-testing via simulate, and
  shipping with a notification destination.
---

# Authoring log alerts

Authoring an alert is a _measurement_ problem, not a guessing problem. You are not trying to be exhaustive — you
are trying to land thresholds that fire 0–3 times per week on real production patterns, on services that matter.

## When to use this skill

- The user asks to "set up alerts" / "suggest alerts" for their project.
- The user wants to evaluate whether a service is producing alertable signal.
- The user has just enabled log alerting and wants a starter set.

## When _not_ to use this skill

- Tuning an alert that already exists — that's a different job (use `posthog:logs-alerts-events-list` to inspect
  fire/resolve cadence and `posthog:logs-alerts-partial-update` to adjust).
- Investigating an active incident — pull rows with `posthog:query-logs`, don't author an alert mid-incident.

## Tools

| Tool                                                                  | Job                                                                           | Where it fits      |
| --------------------------------------------------------------------- | ----------------------------------------------------------------------------- | ------------------ |
| `posthog:logs-services`                                               | Top-25 services in window with log_count, error_count, error_rate, sparkline. | Step 1 — triage.   |
| `posthog:logs-attributes-list` / `posthog:logs-attribute-values-list` | Discover keys/values for narrower filters.                                    | Step 2, optional.  |
| `posthog:logs-count-ranges`                                           | Adaptive time-bucketed counts for a filter.                                   | Step 3 — baseline. |
| `posthog:logs-alerts-simulate-create`                                 | Replay a draft config against `-7d` history with full state machine.          | Step 4 — validate. |
| `posthog:logs-alerts-create`                                          | Persist the alert.                                                            | Step 5 — ship.     |
| `posthog:logs-alerts-destinations-create`                             | Wire the alert to Slack or webhook.                                           | Step 5 — ship.     |

Do **not** call `posthog:query-logs` during authoring. You need distributions, not rows. Reserve `posthog:query-logs` for
the very end if the user asks "show me a sample of what would have fired" — `limit: 10` is plenty.

## Workflow

### 1. Triage — pick candidate services

Call `posthog:logs-services` for the last 24h with no filters. The response is capped at 25 services and includes a
sparkline, so it is small and bounded.

A service is a candidate when **both** are true:

- `log_count` is non-trivial (≥ ~1k in 24h — quieter services produce too little signal to alert on).
- `error_rate` is non-zero, **or** the user has named the service explicitly.

Skip services with high volume but `error_rate == 0` unless the user wants a volume-shape alert (e.g. "warn me
if api-gateway suddenly stops producing logs"). Volume-floor alerts use `threshold_operator: below` and need
different reasoning — see [references/volume-floor-alerts.md](./references/volume-floor-alerts.md).

If the user names a service, treat it as a candidate even without error signal.

### 2. (Optional) Narrow the filter

If a service has many error sub-types, an alert on "all errors" is usually too broad. Use
`posthog:logs-attributes-list` (try `attribute_type: log`) and `posthog:logs-attribute-values-list` to find a discriminator —
common ones are `http.status_code`, `error.type`, `k8s.container.name`. Add the narrowing filter to your draft.

Keep it simple: one severity filter + one or two attribute filters is plenty. Multi-clause filters are
harder to reason about and rarely improve precision.

### 3. Baseline — characterise the candidate over 7 days

Call `posthog:logs-count-ranges` with the candidate's filters, `dateRange: { date_from: "-7d" }`, and
`targetBuckets: 24` (one bucket ≈ 7h). The response gives you bucket counts.

**Do not eyeball the percentiles or scale the threshold to the alert window manually.** Pipe the
count-ranges response into the helper script:

```bash
echo '<count-ranges JSON>' | python3 scripts/baseline_stats.py --window-minutes 5
```

The script returns:

```json
{
  "n_buckets": 12,
  "bucket_minutes": 420.0,
  "alert_window_minutes": 5,
  "stats": { "p50": 12.0, "p95": 71.25, "p99": 126.25, "max": 140 },
  "suggested_threshold_count": 5,
  "rationale": "max(p99=126.25, median*3=36.0, floor=5) scaled from 420m bucket to 5m window",
  "health": []
}
```

Use `suggested_threshold_count` as your starting threshold. Read `health`:

| `health` flag           | What it means                                | What to do                                                                                                 |
| ----------------------- | -------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `sparse:N_of_M_buckets` | Too few non-empty buckets for a 7d baseline. | Widen filter, extend to `-30d`, or skip.                                                                   |
| `empty`                 | All buckets are zero.                        | Skip — no signal.                                                                                          |
| `spiky`                 | `max` is 10×+ `p95`.                         | Count-threshold alerts work well. Proceed.                                                                 |
| `flat`                  | `p95` ≈ `p50`.                               | Be cautious — either no incidents in lookback, or the metric is too smooth. Try a longer lookback or skip. |
| `[]` (empty)            | Healthy distribution.                        | Proceed.                                                                                                   |

### 4. Draft and simulate

Pick a starter draft from these defaults — see [references/threshold-defaults.md](./references/threshold-defaults.md)
for the reasoning:

| Setting               | Default                                     | Notes                                                                 |
| --------------------- | ------------------------------------------- | --------------------------------------------------------------------- |
| `threshold_count`     | `suggested_threshold_count` from the script | Already scaled to the alert window.                                   |
| `threshold_operator`  | `above`                                     | Use `below` only for volume-floor alerts.                             |
| `window_minutes`      | `5`                                         | Allowed: 5, 10, 15, 30, 60. Must match what you passed to the script. |
| `evaluation_periods`  | `3`                                         | M in N-of-M.                                                          |
| `datapoints_to_alarm` | `2`                                         | N in N-of-M. 2-of-3 reduces flap from a single noisy bucket.          |
| `cooldown_minutes`    | `30`                                        | Minimum time between repeat fires.                                    |

Call `posthog:logs-alerts-simulate-create` with these settings and `date_from: "-7d"`. The response gives you `fire_count`
and `resolve_count`.

### 5. Iterate — three rounds, then ship or skip

Target: `fire_count` between 0 and ~3 over `-7d`. If outside the band:

| Outcome                                                         | Adjustment                                                                                           |
| --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `fire_count` = 0 over 7d _and_ the baseline was spiky           | Lower `threshold_count` toward `stats.p95` from the script, or drop to 1-of-2.                       |
| `fire_count` = 0 _and_ the baseline was flat                    | The service has no alertable signal. Skip it; log why.                                               |
| `fire_count` > 5                                                | Raise `threshold_count` toward `stats.max` from the script, or move to 3-of-5 for a smoother window. |
| `fire_count` is fine but resolve_count never matches fire_count | Cooldown is too long, or the underlying state is genuinely sticky. Acceptable for now.               |

When adjusting the threshold, **read values from the script's `stats` block — never recompute percentiles
by hand.**

Cap iteration at **3 simulate calls per candidate**. If you can't land in the band in 3 rounds, the metric
is wrong — either the filter is too broad, the window is wrong, or the service genuinely doesn't have a
threshold-shape signal. Note it and move on.

### 6. Ship — create + attach destination

Once a draft simulates cleanly:

1. Call `posthog:logs-alerts-create` with the validated config. Use a name like `<service> error rate (auto)` so the
   user can see at a glance which alerts came from this skill.
2. Call `posthog:logs-alerts-destinations-create` to wire it to a notification target. **An alert with no destination
   is silent.** Always confirm the channel name or webhook URL with the user before attaching — never wire
   an auto-generated alert to a production channel without explicit confirmation. If the user is unsure,
   suggest a low-traffic testing channel for the first few alerts.

If the user wants alerts created in `enabled: false` state for review-then-flip, pass `enabled: false` to
`-create` and tell them how many drafts you produced.

## Filter shape — required

The `filters` field on `posthog:logs-alerts-create` takes a subset of `LogsViewerFilters` and **must contain at
least one of**:

- `severityLevels` — list of `["trace","debug","info","warn","error","fatal"]`
- `serviceNames` — list of service name strings
- `filterGroup` — property filter group

The same shape goes into `posthog:logs-alerts-simulate-create`'s `filters` field. Match the simulate filters to the alert filters
exactly — otherwise the simulation is testing a different alert than the one you ship.

Example minimum:

```json
{
  "severityLevels": ["error", "fatal"],
  "serviceNames": ["api-gateway"]
}
```

## Token-economy rules

- One `posthog:logs-services` call at the start, not per-candidate.
- One `posthog:logs-count-ranges` call per candidate at `targetBuckets: 24`. Don't go above 30 during authoring.
- ≤ 3 `posthog:logs-alerts-simulate-create` calls per candidate.
- Zero `posthog:query-logs` calls during the authoring loop.
- Prefer reporting a small set of well-validated alerts over a long list of unvalidated drafts.

## Output

Report what you did, in this shape:

- For each shipped alert: name, filters, threshold, simulated fire_count over 7d, destination.
- For each skipped candidate: service name + why (flat baseline, can't land threshold, low volume).
- Total simulate calls made, total alerts created.

The user should be able to read this and decide whether to disable any drafts before they go live.
