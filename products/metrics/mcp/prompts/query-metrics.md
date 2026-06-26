Query server/infrastructure metrics (OTel- or Prometheus-ingested) as bucketed time series. The response is a list of series — `{labels, points: [{time, value}], metric_name, clause}` — where every series shares one time grid (missing buckets are zero-filled). A single ungrouped query returns exactly one series with empty labels.

All parameters are nested inside a `query` object. Two request forms:

- **Single metric (shorthand):** set `metricName` (+ `aggregation`, `filters`, `groupBy`).
- **Multi-clause / formula:** set `clauses: [{name, metricName, aggregation, quantile?, filters?, groupBy?}, ...]` and optionally `formula` (e.g. `"(a - b) / a"` over clause names; `+ - * /` and parentheses; division by zero yields 0). With a formula set, only the formula result series are returned.

# Workflow — follow this order every time

1. **Discover names first.** Call `metric-names-list` with a substring (`value`) before querying — metric names must match exactly, and the returned `metric_type` tells you the right aggregation.
2. **Pick the aggregation by metric type:**
   - `sum` counters (usually `_total`): use `rate` (per-second) or `increase` — both are counter-reset safe and temporality-aware. Do NOT use `sum`/`avg` on cumulative counters; absolute counter values are meaningless.
   - `gauge`: `avg` (typical), `p95`, `sum`.
   - `histogram`: `histogram_quantile` with `quantile` (e.g. 0.95). All selected series must share one bucket layout — narrow with `filters` if you get a bounds-mismatch error.
3. **Narrow with filters.** `filters: [{key, op, value, scope?}]`, ANDed. Ops: `eq`, `neq`, `regex`, `not_regex` (RE2). Leave `scope` at its default `auto` unless you know whether the attribute is per-target (`resource`) or per-datapoint (`attribute`). Negative ops also match rows lacking the key, like Prometheus negative matchers.
4. **Split with groupBy.** `groupBy: [{key}]` returns one series per label value (capped at the 100 largest). `service_name` is always available; discover other keys from a sample query's labels or ask the user.
5. **Control the grid with `interval`.** One of `second, minute, minute_5, minute_15, hour, hour_6, day, week`. Omit to auto-pick (~60 buckets across the range). Use the same interval when comparing windows.

# Investigating an anomaly ("metric X is rising — why?")

1. Query the metric over a window that includes the anomaly AND an equal-length healthy baseline before it (one call, auto interval).
2. Find the onset: the first bucket where the value clearly departs from the baseline range.
3. Re-query grouped by `service_name` (then by other candidate keys) over the same window to see WHICH series moved — a single label value moving points at the culprit; all moving together points at something shared (upstream dependency, infra).
4. Use `formula` for normalized comparisons, e.g. error ratio `errors / requests` instead of raw error counts.
5. Correlate the onset window across signals: query logs (`query-logs`, filtered to the same `service.name` and time window, severity error) and traces (APM span tools, same service/window) to find the cause and its blast radius.

CRITICAL: be minimalist — only include filters/settings essential to the question. Time ranges: `dateFrom` is required, ISO 8601; `dateTo` defaults to now.
