# Threshold defaults — reasoning

The math here is implemented in [`../scripts/baseline_stats.py`](../scripts/baseline_stats.py). The agent
should not reproduce these calculations inline — pipe the `posthog:logs-count-ranges` response into the script and
read `suggested_threshold_count`. This section explains _what the script computes and why_, so you can
sanity-check its output and reason about edge cases.

## `threshold_count = max(p99, median × 3, floor) × (window_minutes / bucket_minutes)`

The bucket-level threshold takes the max of three terms:

1. **p99 of bucket counts.** The 99th percentile of recent buckets is a data-driven "above normal" line.
   Works when the baseline has enough non-empty buckets to compute a percentile.
2. **median × 3.** Catches services where p99 is misleadingly close to the median (flat baselines), or where
   the lookback didn't include any spikes.
3. **floor (default 5).** Alerting on counts of 1 or 2 produces too much noise on small services. Below 5
   matches/window, prefer a different alert shape (e.g. existence-based) or skip.

The bucket-level threshold is then **rate-scaled to the alert window** — a 7h bucket with a threshold of
1000 errors equals ~12 errors per 5-minute window. The script does this scaling; the rationale field shows
the math.

The scaling assumes errors arrive uniformly within a bucket, which is rarely true — a real spike can pack
the entire bucket's count into a single 5-minute window. That's exactly why `posthog:logs-alerts-simulate-create` is the
final arbiter: it replays the alert state machine against actual per-minute history, not the rate-scaled
average.

## `window_minutes = 5`

The default minimum. Reasons to go higher:

- The service is bursty in 5-minute chunks but the _trend_ over 30 minutes is what matters → use 30.
- Notifications at 5-minute resolution would be too noisy for the user (e.g. expected periodic spikes during
  cron) → smooth with a 30 or 60 minute window.

Allowed: `5`, `10`, `15`, `30`, `60`. Don't pick a value not on this list — the API rejects it.

## `evaluation_periods = 3`, `datapoints_to_alarm = 2` (2-of-3)

N-of-M is the cheap, high-signal way to dampen flap. 2-of-3 means: out of the last 3 check intervals, at
least 2 must breach to fire. A single noisy interval doesn't trip the alert. A sustained problem still does.

When to deviate:

- **1-of-1** — fire instantly on a single bucket breach. Use only for incidents you cannot afford to delay
  (e.g. payments service erroring at all).
- **3-of-5** — smoother, slower. Use when the service has known short bursts that are not real incidents.
- Higher than 5 — diminishing returns; if 5 buckets aren't enough signal, the threshold is wrong.

## `cooldown_minutes = 30`

After a fire, suppress repeat fires for 30 minutes. This avoids paging the same channel every check interval
during an ongoing incident — once the alert is firing, the user already knows.

Use 0 for snapshot-style alerts where every breach is independently interesting (rare).

## Avoid these footguns

- **`threshold_operator: below` without justification.** Below-threshold alerts measure absence — useful for
  "service stopped logging" but easy to misuse. If the service has any quiet hours (overnight, weekends),
  a below-threshold alert will fire at 3am every night. See [volume-floor-alerts.md](./volume-floor-alerts.md).
- **Filtering by message text alone (`searchTerm` or `message icontains`).** Brittle to log format changes.
  Prefer a structured attribute (`http.status_code`, `error.type`) when one exists.
- **Filtering by `trace_id`/`span_id`.** Not useful in alerts — these are per-request and never repeat at a
  rate that crosses a meaningful threshold.
