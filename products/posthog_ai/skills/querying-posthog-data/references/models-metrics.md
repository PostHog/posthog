# Metrics (OpenTelemetry metric points)

The `posthog.metrics` table holds OpenTelemetry metric data points from instrumented services. Each row is one observation of a metric (a counter increment, a gauge sample, or a histogram bucket).

**Namespacing:** Reference this table as `posthog.metrics`, not bare `metrics` — it's registered under the `posthog.` namespace in the HogQL database (see `posthog/hogql/database/database.py`). The same applies to `posthog.metric_attributes`. Bare names fail with "Unknown table" at HogQL compile time. (Asymmetric with `logs`, which is registered at root level.)

There is no typed `query-metrics` MCP tool yet — **HogQL is the primary interface for metrics**. The schema mirrors `logs` and `posthog.trace_spans` deliberately so cross-signal joins are cheap, and `trace_id` / `span_id` are first-class columns on every metric row (the OpenTelemetry exemplar pattern).

> ⚠️ **Exemplar extraction is not yet wired up in the ingestion pipeline as of PR [#50936](https://github.com/PostHog/posthog/pull/50936)**. The `trace_id` and `span_id` columns exist on `posthog.metrics`, but `rust/capture-logs/src/metric_record.rs` currently ignores the `_exemplars` field (prefixed with underscore → unused). Every ingested metric row has `trace_id = ''` and `span_id = ''` today. The exemplar-based cross-signal correlation patterns documented below describe the intended capability once exemplar ingestion lands.

## `posthog.metrics`

OpenTelemetry metric points. One row per observation. Backed by ClickHouse `metrics1` (distributed alias `metrics`).

### Columns

| Column                    | Type                                | Description                                                                     |
| ------------------------- | ----------------------------------- | ------------------------------------------------------------------------------- |
| `uuid`                    | String                              | Row UUID                                                                        |
| `team_id`                 | Int32                               | Team this point belongs to                                                      |
| `trace_id`                | String                              | OTel trace ID — exemplar trace. Empty string when no exemplar is attached       |
| `span_id`                 | String                              | OTel span ID — exemplar span                                                    |
| `time_bucket`             | DateTime                            | `toStartOfDay(timestamp)` — first sort key component                            |
| `timestamp`               | DateTime64(6)                       | Observation time                                                                |
| `observed_timestamp`      | DateTime64(6)                       | Ingest time                                                                     |
| `service_name`            | LowCardinality(String)              | Emitting service                                                                |
| `metric_name`             | LowCardinality(String)              | Metric name (e.g. `http.server.duration`, `process.cpu.utilization`)            |
| `metric_type`             | LowCardinality(String)              | `counter`, `gauge`, `histogram`, `summary` (OTel data point kind)               |
| `value`                   | Float64                             | The metric value. For counters/gauges, the observation. For histograms, the sum |
| `count`                   | UInt64                              | For histograms: number of observations in this point. Defaults to 1             |
| `histogram_bounds`        | Array(Float64)                      | For histograms: explicit bucket boundaries                                      |
| `histogram_counts`        | Array(UInt64)                       | For histograms: per-bucket counts (length = `length(histogram_bounds) + 1`)     |
| `unit`                    | LowCardinality(String)              | OTel unit string (e.g. `ms`, `s`, `By`, `1`)                                    |
| `aggregation_temporality` | LowCardinality(String)              | `delta` or `cumulative` (OTel temporality)                                      |
| `is_monotonic`            | Bool                                | For counters: whether the counter is monotonically increasing                   |
| `attributes`              | Map(String, String)                 | Metric-point attributes (label dimensions)                                      |
| `resource_attributes`     | Map(LowCardinality(String), String) | Resource-level attributes (k8s labels, host info)                               |
| `resource_fingerprint`    | UInt64                              | Hash of `resource_attributes`                                                   |
| `instrumentation_scope`   | String                              | Instrumentation library name                                                    |

### Sort key

`(team_id, time_bucket, service_name, metric_name, resource_fingerprint, timestamp)`. Queries that filter on `service_name` + `metric_name` + a time window are very efficient.

### Per-minute aggregate projection

The table has a projection `projection_aggregate_counts` that pre-aggregates by:

`(team_id, time_bucket, toStartOfMinute(timestamp), service_name, metric_name, metric_type, resource_fingerprint)`

with `count() AS event_count`, `sum(value) AS total_value`, `min(value) AS min_value`, `max(value) AS max_value`.

**Queries that group by those exact keys hit the projection and are near-free.** Use this for sparklines, top-N services by metric value, and per-minute breakdowns. The query optimizer picks the projection automatically when the SELECT and GROUP BY match.

### Important notes

- **Unit is metric-dependent.** Always check `unit` — `http.server.duration` may be reported in `ms`, `s`, or `ns` depending on the SDK. Don't assume.
- **`trace_id` is currently always empty string** because exemplar extraction isn't wired up (see warning above). The Rust ingestion uses `String::new()` for both `trace_id` and `span_id`. Filtering `trace_id != ''` correctly excludes unset rows once exemplars start landing.
- **`trace_id` will be base64-encoded** (matching `logs` and `posthog.trace_spans`) once exemplars are populated. Joins to those tables will be direct equality on `trace_id`. Use `hex(tryBase64Decode(trace_id))` to display in hex.
- **Histograms store `histogram_bounds` and `histogram_counts` per row** — you need to expand them for quantile estimation. For a quick p95-ish summary, `value / count` gives the mean per-point.
- **Choose the right temporality.** `delta` metrics measure activity in the interval; `cumulative` metrics are running totals. Summing `value` over time only makes sense for `delta`.
- User HogQL queries on `posthog.metrics` are capped at 50 GB read per query.

## `posthog.metric_attributes`

AggregatingMergeTree rollup of metric attribute values, partitioned by service and 10-minute bucket. Same pattern as `log_attributes` / `posthog.trace_attributes`. Same `posthog.` namespacing rule — reference as `posthog.metric_attributes`.

### Columns

| Column                 | Type                                 | Description                                           |
| ---------------------- | ------------------------------------ | ----------------------------------------------------- |
| `team_id`              | Int32                                | Team                                                  |
| `time_bucket`          | DateTime64(0)                        | 10-minute bucket                                      |
| `service_name`         | LowCardinality(String)               | Emitting service                                      |
| `resource_fingerprint` | UInt64                               | Resource identity hash                                |
| `attribute_key`        | LowCardinality(String)               | Attribute name                                        |
| `attribute_value`      | String                               | Attribute value                                       |
| `attribute_type`       | LowCardinality(String)               | `metric` or `resource`                                |
| `attribute_count`      | SimpleAggregateFunction(sum, UInt64) | Number of metric points where this attribute appeared |

Use this for cheap discovery of which attribute keys exist on which services.

## Common query patterns

**List metric names emitted by a service in the last hour:**

```sql
SELECT metric_name, metric_type, count() AS n
FROM posthog.metrics
WHERE service_name = 'checkout'
  AND timestamp >= now() - INTERVAL 1 HOUR
GROUP BY metric_name, metric_type
ORDER BY n DESC
```

**Per-minute mean value of a non-histogram metric, broken down by service (projection-friendly — `count = 1` per row, so `count()` maps to the projection's `event_count`):**

```sql
SELECT
    toStartOfMinute(timestamp) AS minute,
    service_name,
    sum(value) / count() AS mean_value
FROM posthog.metrics
WHERE metric_name = 'http.server.duration'
  AND timestamp >= now() - INTERVAL 1 HOUR
GROUP BY minute, service_name
ORDER BY minute, mean_value DESC
```

The `projection_aggregate_counts` projection stores `count() AS event_count` and `sum(value) AS total_value`. `sum(count_column)` (the per-row UInt64) is **not** in the projection — using it forces a base-table scan. For histograms (where `count` per row is the bucket observation count), compute the mean separately and don't expect projection acceleration.

**Top services by counter rate in the last hour:**

```sql
SELECT service_name, sum(value) AS total
FROM posthog.metrics
WHERE metric_name = 'http.server.request.count'
  AND metric_type = 'counter'
  AND aggregation_temporality = 'delta'
  AND timestamp >= now() - INTERVAL 1 HOUR
GROUP BY service_name
ORDER BY total DESC
LIMIT 10
```

**Pick the slowest exemplar trace for a metric in a window (exemplar lookup):**

```sql
SELECT argMax(trace_id, value) AS exemplar_trace_id, max(value) AS peak
FROM posthog.metrics
WHERE service_name = 'checkout'
  AND metric_name = 'http.server.duration'
  AND timestamp >= now() - INTERVAL 10 MINUTE
  AND trace_id != ''
```

Pair this with `posthog:apm-trace-get` (or a SQL join on `trace_spans`) to inspect the trace that drove the spike.
