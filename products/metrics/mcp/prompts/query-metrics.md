Run a time-series aggregation over a single OTel metric name. Returns one bucket per time interval with `{time, value}` pairs ordered by time ascending. The bucket width is auto-picked to target ~60 buckets across the requested range (second → minute → 5m → 15m → hour → 6h → day → week).

The metrics product mirrors the logs/tracing shape: metrics flow in through OTLP, land in ClickHouse, and are queried per-team. Trace-connected debugging is possible via each metric data point's `trace_id` / `span_id`, but those are not exposed by this tool — use trace-explorer follow-up calls.

# Workflow — follow this order every time

1. **Discover available metric names first.** Call `metric-names-list` to see what metrics the team has ingested in the last 7 days, with their `metric_type` (`gauge`, `sum`, `counter`, `histogram`, `summary`, `exponential_histogram`). If the user names a specific metric, you can skip this — but verify the name spelled exactly matches before querying.
2. **Pick an aggregation that matches the metric type.** Wrong-aggregation queries produce misleading numbers:
   - `gauge` → `avg` (or `count` to verify samples exist). `sum` aggregates point-in-time snapshots, which is rarely meaningful.
   - `sum` / `counter` → `sum` (or `count` for the number of recorded data points).
   - `histogram` / `summary` / `exponential_histogram` → `p95` for a latency percentile, `avg` for a single average value across the bucket.
3. **Size the range to the question.** Default to `Last 1 hour` for live debugging, `Last 24 hours` for a trend, `Last 7 days` for a baseline. Avoid `Last 30 days` unless the user explicitly asks — the bucket width coarsens to one per day and obscures spikes.
4. **Call `query-metrics`.** Inspect the time-series; if the chart is flat at zero, the metric exists but has no observations in the range (common for `summary` quantiles or rarely-fired counters) — relay that to the user instead of presenting a misleading line.

# Parameters

All parameters are nested inside a `query` object.

- **`metricName`** _(required)_ — exact metric name, e.g. `nodejs_heap_space_size_available_bytes` or `http.server.duration`. Case-sensitive. Use `metric-names-list` to discover.
- **`aggregation`** _(default `sum`)_ — one of `sum`, `avg`, `count`, `p95`. Pick to match metric type per step 2.
- **`dateFrom`** _(required)_ — ISO 8601 timestamp for the lower bound (inclusive).
- **`dateTo`** _(optional)_ — ISO 8601 timestamp for the upper bound (exclusive). Defaults to now if omitted.

# Response shape

```json
{
    "results": [
        { "time": "2026-05-27T14:00:00Z", "value": 12.5 },
        { "time": "2026-05-27T14:01:00Z", "value": 13.1 },
        ...
    ]
}
```

`time` is the bucket start in ISO 8601. `value` is the aggregated number — interpret per the chosen aggregation (`p95` is in the metric's native unit, `count` is samples per bucket).

# Common mistakes to avoid

- **Aggregating a gauge with `sum`** — produces a number that looks impressive but is meaningless (sum of point-in-time snapshots). Use `avg`.
- **Hitting `query-metrics` without discovering the name first** — substring guesses miss real metrics. Always `metric-names-list` if the user hasn't given the exact name.
- **Requesting a range wider than needed** — the bucket width coarsens past 60 buckets, hiding short spikes. Use multiple narrower queries instead of one 30-day query when investigating an incident.

CRITICAL: Be minimalist. Only set parameters that are essential. The default aggregation (`sum`) and auto-picked bucket width are usually right for "counter" and "sum" type metrics; gauges and histograms need an explicit `aggregation` override.
