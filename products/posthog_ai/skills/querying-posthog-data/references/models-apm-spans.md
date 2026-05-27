# APM / tracing (OpenTelemetry spans)

The `posthog.trace_spans` table holds OpenTelemetry span data from instrumented services. Each row is one span — a unit of work in a distributed trace. Spans within the same trace share a `trace_id`; the parent-child hierarchy is reconstructed via `parent_span_id` → `span_id`.

**Namespacing:** Reference this table as `posthog.trace_spans`, not bare `trace_spans` — it's registered under the `posthog.` namespace in the HogQL database (see `posthog/hogql/database/database.py`). The same applies to `posthog.trace_attributes`. Bare names fail with "Unknown table" at HogQL compile time. (Asymmetric with `logs`, which is registered at root level — `logs` works without a prefix.)

**Prefer the typed tools when they fit:** `posthog:query-apm-spans` for span listing with structured filters, `posthog:apm-trace-get` for full-trace fetches, `posthog:apm-spans-aggregate` / `posthog:apm-spans-tree` for aggregations. Reach for HogQL when you need cross-signal joins (with `logs` or `posthog.metrics` by `trace_id`), exemplar lookups, or aggregations the typed tools don't expose.

## `posthog.trace_spans`

OpenTelemetry spans. One row per span. Backed by ClickHouse `trace_spans_distributed`.

### Columns

| Column                  | Type                                | Description                                                                          |
| ----------------------- | ----------------------------------- | ------------------------------------------------------------------------------------ |
| `uuid`                  | String                              | Row UUID (not the OTel span_id)                                                      |
| `team_id`               | Int32                               | Team this span belongs to                                                            |
| `trace_id`              | String                              | OTel trace ID (24-char base64-encoded 16 bytes). Same on every span in the trace     |
| `span_id`               | String                              | OTel span ID (12-char base64-encoded 8 bytes). Unique within a trace                 |
| `parent_span_id`        | String                              | OTel parent span ID (12-char base64). `'AAAAAAAAAAA='` (8 zero bytes) for root spans |
| `is_root_span`          | Bool                                | Convenience flag — prefer this over string-matching `parent_span_id`                 |
| `name`                  | LowCardinality(String)              | Span name (operation name)                                                           |
| `kind`                  | Int8                                | OTel SpanKind: 0 Unspecified, 1 Internal, 2 Server, 3 Client, 4 Producer, 5 Consumer |
| `status_code`           | Int16                               | OTel StatusCode: 0 Unset, 1 OK, 2 Error                                              |
| `service_name`          | LowCardinality(String)              | Emitting service                                                                     |
| `timestamp`             | DateTime64(6)                       | Span start time                                                                      |
| `end_time`              | DateTime64(6)                       | Span end time                                                                        |
| `observed_timestamp`    | DateTime64(6)                       | Ingest time                                                                          |
| `duration_nano`         | UInt64                              | Span duration in **nanoseconds** (1 s = 1_000_000_000)                               |
| `attributes`            | Map(String, String)                 | Span-level attributes (e.g. `http.method`, `http.status_code`, `db.statement`)       |
| `resource_attributes`   | Map(LowCardinality(String), String) | Resource-level attributes (k8s labels, deployment info, host)                        |
| `resource_fingerprint`  | UInt64                              | Hash of `resource_attributes` — cheap equality filter                                |
| `instrumentation_scope` | String                              | Instrumentation library name                                                         |
| `time_bucket`           | DateTime                            | `toStartOfDay(timestamp)` — first sort key component                                 |

### Sort key

`(team_id, time_bucket, service_name, resource_fingerprint, status_code, name, timestamp)`. Queries that filter on `service_name` + `time_bucket` are very efficient. Filters on `name` further narrow the read.

### Important notes

- **Durations are nanoseconds.** Filter `duration_nano > 1000000000` for spans longer than 1 second.
- **`status_code == 2` is Error.** Use `status_code = 2` (not the string `"ERROR"`).
- **`trace_id`, `span_id`, `parent_span_id` are base64-encoded bytes**, not hex. The MCP layer (`posthog:query-apm-spans`, `posthog:apm-trace-get`) converts to hex via `hex(tryBase64Decode(...))` for display. Raw HogQL queries against this table see the base64 form.
- **`parent_span_id` of a root span** is `'AAAAAAAAAAA='` (12-char base64 of 8 zero bytes), not null. **Use `is_root_span` to find trace entries** — don't string-match the padding.
- **Use `hex(tryBase64Decode(trace_id))` to display trace_ids in hex** for human-readable output.
- Cross-signal joins by `trace_id` work against `logs` (both store base64). For `posthog.metrics`, exemplar extraction is not yet wired up in the ingestion pipeline — see the metrics reference for the current state.
- User HogQL queries on `posthog.trace_spans` are capped at 50 GB read per query.

## `posthog.trace_attributes`

AggregatingMergeTree rollup of span attribute values, partitioned by service and 10-minute bucket. Backs the attribute discovery endpoints used by `posthog:apm-attributes-list` and `posthog:apm-attribute-values-list`. Same `posthog.` namespacing rule — reference as `posthog.trace_attributes`.

### Columns

| Column                 | Type                                 | Description                                   |
| ---------------------- | ------------------------------------ | --------------------------------------------- |
| `team_id`              | Int32                                | Team                                          |
| `time_bucket`          | DateTime64(0)                        | 10-minute bucket                              |
| `service_name`         | LowCardinality(String)               | Emitting service                              |
| `resource_fingerprint` | UInt64                               | Resource identity hash                        |
| `attribute_key`        | LowCardinality(String)               | Attribute name                                |
| `attribute_value`      | String                               | Attribute value                               |
| `attribute_type`       | LowCardinality(String)               | `span_attribute` or `span_resource_attribute` |
| `attribute_count`      | SimpleAggregateFunction(sum, UInt64) | Number of spans where this attribute appeared |

Prefer `posthog:apm-attributes-list` / `posthog:apm-attribute-values-list` over querying this table directly — they handle the aggregation correctly.

## Common query patterns

**Top-10 slowest root spans for a service in the last hour** (convert `trace_id` to hex for display):

```sql
SELECT name, duration_nano, hex(tryBase64Decode(trace_id)) AS trace_id, timestamp
FROM posthog.trace_spans
WHERE service_name = 'checkout'
  AND is_root_span
  AND timestamp >= now() - INTERVAL 1 HOUR
ORDER BY duration_nano DESC
LIMIT 10
```

**Error rate per service in the last hour:**

```sql
SELECT
    service_name,
    countIf(status_code = 2) AS errors,
    count() AS total,
    errors / total AS error_rate
FROM posthog.trace_spans
WHERE timestamp >= now() - INTERVAL 1 HOUR
GROUP BY service_name
HAVING total > 100
ORDER BY error_rate DESC
```

**Find traces touching both `payments` and `inventory` services:**

```sql
SELECT hex(tryBase64Decode(trace_id)) AS trace_id, min(timestamp) AS started, count() AS span_count
FROM posthog.trace_spans
WHERE service_name IN ('payments', 'inventory')
  AND timestamp >= now() - INTERVAL 1 HOUR
GROUP BY trace_id
HAVING uniqExact(service_name) = 2
ORDER BY started DESC
LIMIT 20
```
