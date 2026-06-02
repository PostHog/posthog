# Logs

## `logs` (data plane)

OpenTelemetry log entries. One row per log line. Backed by ClickHouse `logs_distributed`.

**Prefer the typed tool when it fits:** `posthog:query-logs` for filtered list queries (with the encoded discovery → narrow → count → drill-down workflow). Reach for HogQL when you need cross-signal joins (with `posthog.trace_spans` or `posthog.metrics` by `trace_id`) or aggregations the typed tool doesn't expose.

**Namespacing:** `logs` and `log_attributes` are registered at the HogQL root level — reference them as bare names. (Asymmetric with `posthog.trace_spans` and `posthog.metrics`, which require the `posthog.` namespace prefix.)

### Columns

| Column                  | Type                                | Description                                                                                        |
| ----------------------- | ----------------------------------- | -------------------------------------------------------------------------------------------------- |
| `uuid`                  | String                              | Row UUID                                                                                           |
| `team_id`               | Int32                               | Team this log belongs to                                                                           |
| `trace_id`              | String                              | OTel trace ID (24-char base64-encoded 16 bytes). `'AAAAAAAAAAAAAAAAAAAAAA=='` when unset, not null |
| `span_id`               | String                              | OTel span ID (12-char base64-encoded 8 bytes). `'AAAAAAAAAAA='` when unset                         |
| `body`                  | String                              | Log message. Also exposed as `message`                                                             |
| `severity_text`         | LowCardinality(String)              | `trace`, `debug`, `info`, `warn`, `error`, `fatal`                                                 |
| `severity_number`       | Int32                               | OTel severity number (lower = less severe)                                                         |
| `level`                 | LowCardinality(String)              | Alias for `severity_text`                                                                          |
| `service_name`          | LowCardinality(String)              | Emitting service                                                                                   |
| `attributes`            | Map(String, String)                 | Log-level attributes (e.g. `http.method`, `error.type`)                                            |
| `resource_attributes`   | Map(LowCardinality(String), String) | Resource-level attributes (k8s labels, deployment info)                                            |
| `resource_fingerprint`  | UInt64                              | Hash of `resource_attributes`                                                                      |
| `instrumentation_scope` | String                              | Instrumentation library                                                                            |
| `event_name`            | String                              | OTel event name (often empty)                                                                      |
| `time_bucket`           | DateTime                            | `toStartOfDay(timestamp)`                                                                          |
| `timestamp`             | DateTime64(9)                       | Log time                                                                                           |
| `observed_timestamp`    | DateTime64(9)                       | Ingest time                                                                                        |

### Sort key

`(team_id, service_name, toUnixTimestamp(timestamp))`. Queries that filter on `service_name` + a time window are very efficient. **Never query without a `service_name` filter and a time window** — unfiltered queries can scan terabytes. `resource_attributes` is a Map column outside the sort key, so a `resource_attributes` filter alone does **not** prune granules the way `service_name` does and is no substitute for it.

### Important notes

- **`trace_id` and `span_id` are base64-encoded bytes**, not hex. The displayed hex form (e.g. `21EDB3A025A9ECD32ADF3E5D7548A4F4`) comes from the API layer via `hex(tryBase64Decode(trace_id))`. Raw HogQL queries see the 24-character base64 form (e.g. `21EDB3A025A9ECD32ADF3E5D7548A4F4` becomes `Ie2zoCWp7NMq3z5ddUik9A==`).
- **Unset `trace_id` is `'AAAAAAAAAAAAAAAAAAAAAA=='`** (16 zero bytes encoded), not the hex zero-padded form. Use `trace_id != 'AAAAAAAAAAAAAAAAAAAAAA=='` to find logs with trace context. Or use the explicit decode: `tryBase64Decode(trace_id) != unhex('00000000000000000000000000000000')`.
- **Use `hex(tryBase64Decode(trace_id))` to display trace_ids in hex** for human-readable output.
- **Prefer `severity_text` over `severity_number` / `level`** for human-readable filters.
- Cross-signal joins by `trace_id` work against `posthog.trace_spans` (both store base64) and `posthog.metrics` _once exemplar extraction is wired up in ingestion_ — see the metrics reference for the current state.
- User HogQL queries on `logs` are capped at 50 GB read per query.

## `log_attributes`

AggregatingMergeTree rollup of log attribute values, partitioned by service and 10-minute bucket. Same pattern as `trace_attributes` / `metric_attributes`.

| Column                 | Type                                 | Description                                  |
| ---------------------- | ------------------------------------ | -------------------------------------------- |
| `team_id`              | Int32                                | Team                                         |
| `time_bucket`          | DateTime64(0)                        | 10-minute bucket                             |
| `service_name`         | LowCardinality(String)               | Emitting service                             |
| `resource_fingerprint` | UInt64                               | Resource identity hash                       |
| `attribute_key`        | LowCardinality(String)               | Attribute name                               |
| `attribute_value`      | String                               | Attribute value                              |
| `attribute_type`       | LowCardinality(String)               | `log` or `resource`                          |
| `attribute_count`      | SimpleAggregateFunction(sum, UInt64) | Number of logs where this attribute appeared |

Prefer `posthog:logs-attributes-list` / `posthog:logs-attribute-values-list` over querying this table directly — they handle the aggregation correctly.

---

## LogsView (`system.logs_views`)

Saved log views — named filter configurations that users create to quickly access frequently-used log queries.

### Columns

| Column       | Type              | Nullable | Description                                                           |
| ------------ | ----------------- | -------- | --------------------------------------------------------------------- |
| `id`         | uuid              | NOT NULL | Primary key                                                           |
| `team_id`    | integer           | NOT NULL | Team this view belongs to                                             |
| `short_id`   | varchar(12)       | NOT NULL | URL-friendly short identifier                                         |
| `name`       | varchar(400)      | NOT NULL | Display name                                                          |
| `filters`    | jsonb             | NOT NULL | Saved filter criteria (severity levels, service names, filter groups) |
| `pinned`     | boolean           | NOT NULL | Whether the view is pinned for quick access                           |
| `created_at` | timestamp with tz | NOT NULL | Creation timestamp                                                    |
| `updated_at` | timestamp with tz | NOT NULL | Last update timestamp                                                 |

### Key Relationships

- Views belong to a **Team** (`team_id`)
- The `filters` field stores the same filter structure used by the logs viewer UI

### Important Notes

- The `short_id` is auto-generated and unique per team
- `filters` typically contains `severityLevels`, `serviceNames`, and `filterGroup` keys

---

## LogsAlertConfiguration (`system.logs_alerts`)

Alerts that monitor log volume and notify users when thresholds are breached. Uses an N-of-M evaluation model (similar to AWS CloudWatch alarms).

### Columns

| Column                   | Type              | Nullable | Description                                                         |
| ------------------------ | ----------------- | -------- | ------------------------------------------------------------------- |
| `id`                     | uuid              | NOT NULL | Primary key                                                         |
| `team_id`                | integer           | NOT NULL | Team this alert belongs to                                          |
| `name`                   | varchar(255)      | NOT NULL | Alert name                                                          |
| `enabled`                | boolean           | NOT NULL | Whether the alert is actively evaluated                             |
| `filters`                | jsonb             | NOT NULL | Log filter criteria (severity levels, service names, filter groups) |
| `threshold_count`        | integer           | NOT NULL | Number of log entries that triggers the alert                       |
| `threshold_operator`     | varchar(10)       | NOT NULL | `above` or `below`                                                  |
| `window_minutes`         | integer           | NOT NULL | Time window in minutes to evaluate                                  |
| `check_interval_minutes` | integer           | NOT NULL | How often the alert is checked (minutes)                            |
| `state`                  | varchar(20)       | NOT NULL | Current alert state (see State Values below)                        |
| `evaluation_periods`     | integer           | NOT NULL | Number of periods in the evaluation window (M in N-of-M)            |
| `datapoints_to_alarm`    | integer           | NOT NULL | Breaches needed to fire (N in N-of-M)                               |
| `cooldown_minutes`       | integer           | NOT NULL | Minutes to wait after firing before re-evaluating                   |
| `snooze_until`           | timestamp with tz | NULL     | Snooze expiry (UTC)                                                 |
| `next_check_at`          | timestamp with tz | NULL     | When the next evaluation is scheduled                               |
| `last_notified_at`       | timestamp with tz | NULL     | When subscribers were last notified                                 |
| `last_checked_at`        | timestamp with tz | NULL     | When the alert was last evaluated                                   |
| `consecutive_failures`   | integer           | NOT NULL | Number of consecutive evaluation failures                           |
| `created_at`             | timestamp with tz | NOT NULL | Creation timestamp                                                  |
| `updated_at`             | timestamp with tz | NOT NULL | Last update timestamp                                               |

### State Values

| State             | Description                                           |
| ----------------- | ----------------------------------------------------- |
| `not_firing`      | Alert is within normal thresholds                     |
| `firing`          | Threshold breached, notifications sent                |
| `pending_resolve` | Was firing, waiting for confirmation that it resolved |
| `errored`         | Evaluation failed                                     |
| `snoozed`         | Temporarily silenced until `snooze_until`             |

### Key Relationships

- Alerts belong to a **Team** (`team_id`)
- Alert checks are stored in `LogsAlertEvent` (not exposed as a system table)

### Important Notes

- The N-of-M model: alert fires when `datapoints_to_alarm` (N) out of the last `evaluation_periods` (M) checks breach the threshold
- `datapoints_to_alarm` must be <= `evaluation_periods`
- Disabled alerts automatically have their state set to `not_firing`

---

## Common Query Patterns

### Data plane (`logs`)

**Top-10 noisiest services by error log volume in the last hour:**

```sql
SELECT service_name, count() AS errors
FROM logs
WHERE severity_text IN ('error', 'fatal')
  AND timestamp >= now() - INTERVAL 1 HOUR
GROUP BY service_name
ORDER BY errors DESC
LIMIT 10
```

**Logs in a specific trace** (input the hex form; convert internally):

```sql
SELECT timestamp, severity_text, service_name, body
FROM logs
WHERE trace_id = base64Encode(unhex('<hex_trace_id>'))
ORDER BY timestamp
```

If you already have the trace_id in base64 form (e.g. selected directly from the table), compare it as-is:

```sql
SELECT timestamp, severity_text, service_name, body
FROM logs
WHERE trace_id = 'Ie2zoCWp7NMq3z5ddUik9A=='
ORDER BY timestamp
```

**Logs matching a body substring on a service in a time window:**

```sql
SELECT timestamp, severity_text, body
FROM logs
WHERE service_name = 'api-gateway'
  AND timestamp >= now() - INTERVAL 6 HOUR
  AND body ILIKE '%connection refused%'
ORDER BY timestamp DESC
LIMIT 100
```

### Control plane

**List all saved log views:**

```sql
SELECT id, name, short_id, pinned, created_at
FROM system.logs_views
ORDER BY created_at DESC
LIMIT 20
```

**Find pinned log views:**

```sql
SELECT id, name, short_id
FROM system.logs_views
WHERE pinned
ORDER BY name
```

**List active log alerts:**

```sql
SELECT id, name, state, threshold_count, threshold_operator, window_minutes
FROM system.logs_alerts
WHERE enabled
  AND state != 'snoozed'
ORDER BY created_at DESC
```

**Find firing log alerts:**

```sql
SELECT id, name, state, last_checked_at, last_notified_at
FROM system.logs_alerts
WHERE state = 'firing'
ORDER BY last_notified_at DESC
```

**Count log alerts by state:**

```sql
SELECT state, count() AS count
FROM system.logs_alerts
WHERE enabled
GROUP BY state
ORDER BY count DESC
```

**Find errored or failing log alerts:**

```sql
SELECT id, name, state, consecutive_failures, last_checked_at
FROM system.logs_alerts
WHERE state = 'errored' OR consecutive_failures > 0
ORDER BY consecutive_failures DESC
```
