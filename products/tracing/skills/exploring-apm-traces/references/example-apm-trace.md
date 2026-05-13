# APM trace HogQL templates

Templates for cases the MCP tools (`query-apm-spans`, `apm-trace-get`) don't cover well. Run via `posthog:execute-sql`.

The schema and column names match `posthog.trace_spans` and `posthog.trace_attributes` exactly — they live behind the same backend that serves the MCP tools (see [products/tracing/backend/logic.py](../../../backend/logic.py)).

**Always set a date range.** `time_bucket` is the partition key; without filtering on it queries scan the whole table.

**Trace IDs are stored base64-encoded** in `trace_spans.trace_id`. Wrap with `hex(tryBase64Decode(trace_id))` to read them as hex, and `base64Encode(unhex('<hex>'))` to filter for a specific trace.

**Durations are nanoseconds.** Divide by `1_000_000` for milliseconds.

## p95 latency by service

```sql
SELECT
    service_name,
    count() AS span_count,
    quantile(0.50)(duration_nano) / 1_000_000 AS p50_ms,
    quantile(0.95)(duration_nano) / 1_000_000 AS p95_ms,
    quantile(0.99)(duration_nano) / 1_000_000 AS p99_ms,
    countIf(status_code = 2) AS error_count
FROM posthog.trace_spans
WHERE time_bucket >= toStartOfDay(now() - INTERVAL 1 DAY)
  AND time_bucket <= toStartOfDay(now())
  AND is_root_span
GROUP BY service_name
ORDER BY p95_ms DESC
LIMIT 50
```

`is_root_span` keeps this to the trace entry — for per-operation breakdowns swap in `name` instead.

## Slow root traces over the last hour

```sql
SELECT
    hex(tryBase64Decode(trace_id)) AS trace_id,
    service_name,
    name,
    duration_nano / 1_000_000 AS duration_ms,
    status_code,
    timestamp
FROM posthog.trace_spans
WHERE time_bucket >= toStartOfDay(now() - INTERVAL 1 HOUR)
  AND time_bucket <= toStartOfDay(now())
  AND timestamp >= now() - INTERVAL 1 HOUR
  AND is_root_span
  AND duration_nano > 1_000_000_000  -- 1 second
ORDER BY duration_nano DESC
LIMIT 50
```

## Error traces grouped by service+operation

```sql
SELECT
    service_name,
    name,
    count() AS error_count,
    uniq(trace_id) AS distinct_traces,
    max(timestamp) AS last_seen
FROM posthog.trace_spans
WHERE time_bucket >= toStartOfDay(now() - INTERVAL 1 DAY)
  AND time_bucket <= toStartOfDay(now())
  AND status_code = 2
GROUP BY service_name, name
ORDER BY error_count DESC
LIMIT 50
```

## Inspect every span in one specific trace

When you already have a hex trace ID and want raw column data without the MCP tool's response shape:

```sql
SELECT
    hex(tryBase64Decode(span_id)) AS span_id,
    hex(tryBase64Decode(parent_span_id)) AS parent_span_id,
    name,
    service_name,
    kind,
    status_code,
    duration_nano / 1_000_000 AS duration_ms,
    timestamp
FROM posthog.trace_spans
WHERE time_bucket >= toStartOfDay(now() - INTERVAL 1 DAY)
  AND time_bucket <= toStartOfDay(now())
  AND trace_id = base64Encode(unhex('REPLACE_WITH_HEX_TRACE_ID'))
ORDER BY timestamp ASC
LIMIT 1000
```

## Discover available attributes for a date range

`apm-attributes-list` is the right tool for the agent in most cases. Use this when you need counts (e.g. "which attributes have the most distinct values?") or need to join attributes back to spans.

```sql
SELECT
    attribute_type,
    attribute_key,
    sum(attribute_count) AS occurrences
FROM posthog.trace_attributes
WHERE time_bucket >= toStartOfDay(now() - INTERVAL 1 DAY)
  AND time_bucket <= toStartOfDay(now())
GROUP BY attribute_type, attribute_key
ORDER BY occurrences DESC
LIMIT 100
```

`attribute_type` is one of `span` (built-in), `span_attribute` (custom span-level), or `span_resource_attribute` (resource-level).

## Reminders

- `time_bucket` is the partition column — every query must filter it. `timestamp` is the precise event time and should be filtered separately for sub-day windows.
- Spans for one trace can sit in multiple `time_bucket` partitions if the trace crossed midnight UTC.
- The `posthog.trace_spans` table doesn't carry attributes inline — join to `posthog.trace_attributes` if you need them, but it's cheaper to start with `apm-attribute-values-list`.
