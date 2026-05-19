# Cross-signal correlation (metric exemplar → trace → logs)

Use when investigating a metric anomaly (latency spike, error rate jump) and you want to inspect a representative trace and the logs from that request in one round trip.

The three observability tables — `posthog.metrics`, `posthog.trace_spans`, `logs` — share `trace_id` as a join key. `posthog.metrics` carries an exemplar `trace_id` on every point when the SDK attached one (OpenTelemetry exemplar pattern). Pulling all three together is one query.

**Namespacing:** `logs` is registered at the HogQL root level; `posthog.trace_spans` and `posthog.metrics` live under the `posthog.` namespace and must be referenced with the prefix. Bare names fail.

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
