# Cross-signal correlation (metric exemplar → trace → logs)

Use when investigating a metric anomaly (latency spike, error rate jump) and you want to inspect a representative trace and the logs from that request in one round trip.

The three observability tables — `posthog.metrics`, `posthog.trace_spans`, `logs` — share `trace_id` as a join key. The schema is wired so `posthog.metrics` can carry an exemplar `trace_id` on every point when the SDK attached one (OpenTelemetry exemplar pattern).

**Namespacing:** `logs` is registered at the HogQL root level; `posthog.trace_spans` and `posthog.metrics` live under the `posthog.` namespace and must be referenced with the prefix. Bare names fail.

**`trace_id` format:** All three tables store `trace_id` as base64-encoded 16 bytes. Joins are direct equality (no decoding needed). Use `hex(tryBase64Decode(trace_id))` to display in hex.

> **Exemplars are sparse.** Only metric points whose SDK attached an exemplar carry a `trace_id`. An empty result from the query below means no spans or logs matched the chosen trace (the trace may not be exported or retained); it does not prove the metric has no exemplars. Count `trace_id != ''` rows in `posthog.metrics` for the same metric and window first. Use the span-anchored alternative further down when that count is zero, or when the exemplar traces have no retained spans or logs. In the second case, try the next exemplar from the variant query below before you fall back.

## Pattern

1. **Locate the spike** in `metrics` for a specific `(service, metric, time window)`.
2. **Pick an exemplar** — `argMax(trace_id, value)` returns the trace_id from the row with the highest value.
3. **Fetch spans and logs** for that trace_id in a single `UNION ALL`, ordered by timestamp so the timeline interleaves.

## Query

```sql
WITH exemplar AS (
    SELECT argMax(trace_id, value) AS trace_id
    FROM posthog.metrics
    WHERE service_name = 'checkout'
      AND metric_name = 'http.server.duration'
      AND timestamp >= now() - INTERVAL 15 MINUTE
      AND trace_id != ''
)
SELECT
    'span' AS source,
    name AS detail,
    service_name,
    duration_nano,
    status_code,
    NULL AS severity_number,
    timestamp
FROM posthog.trace_spans
WHERE trace_id = (SELECT trace_id FROM exemplar)

UNION ALL

SELECT
    'log',
    body,
    service_name,
    NULL,
    NULL,
    severity_number,
    timestamp
FROM logs
WHERE trace_id = (SELECT trace_id FROM exemplar)

ORDER BY timestamp
```

## Notes

- **`argMax(trace_id, value)` is cheap** because the per-minute projection on `posthog.metrics` pre-aggregates by `(service_name, metric_name, ...)`. Constrain the time window tightly (15 minutes is plenty for a spike).
- **Filter `trace_id != ''`** — metric points without an exemplar use empty string, not null.
- **`UNION ALL` (not `UNION`)** — `UNION` deduplicates and adds cost.
- **`status_code = 2` is Error** in `posthog.trace_spans` (OTel semantics). Use this column to flag error spans inline in the result.
- If you need to drill into the span tree visually, take the resulting `trace_id` and call `posthog:apm-trace-get` to get the full waterfall.

## Fallback: span-anchored correlation

When the metric has no exemplar points in the window, or none of its exemplar traces has retained spans or logs, anchor on a span instead. Find an interesting trace (slowest error, longest duration, specific service), then pull its logs.

```sql
WITH slow_error_trace AS (
    SELECT trace_id
    FROM posthog.trace_spans
    WHERE service_name = 'checkout'
      AND is_root_span
      AND status_code = 2
      AND timestamp >= now() - INTERVAL 1 HOUR
    ORDER BY duration_nano DESC
    LIMIT 1
)
SELECT
    'span' AS source,
    name AS detail,
    service_name,
    duration_nano,
    status_code,
    NULL AS severity_number,
    timestamp
FROM posthog.trace_spans
WHERE trace_id = (SELECT trace_id FROM slow_error_trace)

UNION ALL

SELECT
    'log',
    body,
    service_name,
    NULL,
    NULL,
    severity_number,
    timestamp
FROM logs
WHERE trace_id = (SELECT trace_id FROM slow_error_trace)

ORDER BY timestamp
```

`trace_id` is base64 in both tables, so the equality join works directly.

## Variants

**Pick a sample of exemplar traces, not just one:**

```sql
SELECT trace_id, max(value) AS peak
FROM posthog.metrics
WHERE service_name = 'checkout'
  AND metric_name = 'http.server.duration'
  AND timestamp >= now() - INTERVAL 15 MINUTE
  AND trace_id != ''
GROUP BY trace_id
ORDER BY peak DESC
LIMIT 5
```

**Find services with the biggest error-rate jump and pick an exemplar trace per service:**

```sql
SELECT
    service_name,
    countIf(status_code = 2) / count() AS error_rate,
    argMax(trace_id, status_code = 2) AS sample_error_trace
FROM posthog.trace_spans
WHERE timestamp >= now() - INTERVAL 1 HOUR
  AND is_root_span
GROUP BY service_name
HAVING count() > 100
ORDER BY error_rate DESC
LIMIT 10
```

`sample_error_trace` is then a candidate for `posthog:apm-trace-get` or a `logs` lookup by `trace_id`.
