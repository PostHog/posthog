---
name: investigating-metric-anomalies
description: Investigates server/infrastructure metric anomalies in PostHog Metrics — from "this metric is rising/dropping/spiking" or a fired alert to a probable cause with evidence. Use when asked why a metric looks wrong (ingestion lag rising, error rate spiking, latency degrading, queue depth growing, throughput dropping), when an alert fires on an OTel/Prometheus metric, or for any incident triage that starts from a metric symptom. Composes characterize-metric-anomaly, query-metrics, and metric-names-list with logs (query-logs) and traces (APM span tools) for cross-signal root-cause correlation.
---

# Investigating metric anomalies

The job: go from a metric symptom ("ingestion lag is rising") to a probable cause with evidence, fast. The metric tells you _what_ and _when_; logs and traces tell you _why_. Follow the loop below — it front-loads the cheap, high-information calls and only fans out when the blast radius is unclear.

## The loop

### 1. Pin down the metric

If you have the exact metric name, skip ahead. Otherwise call `metric-names-list` with a substring from the symptom (`lag`, `error`, `latency`, `queue`). The returned `metric_type` decides the lens: counters (`sum`) are only meaningful as `rate`/`increase`, gauges as `avg`, histograms as `histogram_quantile`.

### 2. Characterize first — one call, three answers

Call `characterize-metric-anomaly` with the metric name and `anomalyFrom` (the alert fire time, or when the user says it started looking wrong; subtract some margin if unsure). It compares against the preceding window by default and answers:

- **How bad:** `direction`, `change_ratio`, `anomaly_peak` vs `baseline_mean`. If `direction` is `flat`, your window or metric is wrong — widen the window, or compare against the same window yesterday via `baselineFrom`/`baselineTo` (daily-pattern metrics often look "anomalous" against the immediately-preceding hours).
- **When:** `onset_time` — treat this timestamp as the pivot for everything that follows.
- **Where:** `top_movers` — label values whose behavior changed. One mover (a single pod, shard, or endpoint) means a localized culprit; everything moving together means a shared cause (an upstream dependency, a deploy, infra).

### 3. Sharpen with targeted metric queries

Use `query-metrics` to test the hypotheses the report raises:

- Drill a mover: re-query with `filters` pinning the suspicious label value, grouped by a second key, to localize further (pod → container, endpoint → status code).
- Normalize: a rising error count means nothing if traffic doubled — use `clauses` + `formula` (`errors / requests`) to separate rate changes from volume changes.
- Check the neighbors: query the obvious companion metrics over the same window (for lag: throughput and error counters of the same service; for latency: request rate and saturation gauges). Use the same `interval` so the grids align visually.

### 4. Correlate across signals at the onset

Pivot into logs and traces using the **same service and a window bracketing `onset_time`** (a few buckets before, through the peak):

- **Logs:** use `query-logs` (follow its own discover-first workflow) filtered to the implicated `service.name` and window, severity `error` first, then `warn`. Restarts, crash loops, connection errors, and deploy markers right before onset are the classic causes. Widen to other services in the request path if the service's own logs are clean.
- **Traces:** use the APM span tools (`query-apm-spans` etc.) for the same service/window — slow or erroring spans show _which dependency_ degraded, and a `trace_id` from an exemplar or log line links a concrete request across all three signals.

### 5. Conclude with evidence, not vibes

State: the symptom (metric, magnitude, onset), the probable cause (what you found in logs/traces and how its timing aligns with the onset), the blast radius (which services/labels are affected, from the movers and grouped queries), and the confidence level. If the cause is still ambiguous, say which hypothesis the evidence favors and what would disambiguate (e.g. "the lag began draining at 20:12 — consistent with a consumer restart; check who restarted it").

## Worked example: "ingestion lag is rising — why?"

1. `metric-names-list` with `value: "lag"` → `logs_rate_limiter_message_lag_seconds` (histogram) and friends.
2. `characterize-metric-anomaly` on it with `anomalyFrom` = alert time → direction `up`, change ratio 40x, `onset_time` 20:10, top mover `service_name = logs-ingestion` (the other services' lag stayed flat) — so the logs consumer specifically is behind, not the whole pipeline.
3. `query-metrics`: `rate` of the consumer's throughput counter over the same window → throughput was **zero** during the gap and spiked after onset: the consumer wasn't slow, it was _down_, and the "rising lag" is it draining the backlog.
4. `query-logs` for `service.name = logs-ingestion` (and its neighbors) around 20:00–20:15 → process exit + restart lines at the gap boundaries.
5. Conclusion: consumer outage 20:01–20:10 (restart visible in logs); lag spike is backlog drain, self-recovering; affected signal: logs freshness only — no data loss (topic retained messages). Evidence: zero throughput during the window, message-age spike equal to outage duration, restart log lines.

## Pitfalls

- Counters reset on process restart — `rate`/`increase` already handle this; never eyeball raw cumulative counter values.
- A metric that stops reporting is not "zero" — a gap in `series` with `top_movers` showing a vanished label value means the _emitter_ died; pivot to logs immediately.
- Don't trust a single aggregation: a flat `avg` can hide a screaming `p95`. For latency-like gauges and histograms, characterize the tail too.
- Scraped Prometheus metrics arrive ~15–60s behind real time; don't read the last bucket of a series as "current".
