Executes HogQL — PostHog's variant of SQL that supports most of ClickHouse SQL. "HogQL" and "SQL" are used interchangeably.

{guidelines}

### When to use `execute-sql`

**Use `query-*` tools whenever the question maps to a supported insight type.** These tools produce typed, saveable insights; SQL forfeits that.
Reach for `execute-sql` only when no `query-*` tool can express the question:

- **Searching or listing existing PostHog entities** — insights, dashboards, cohorts, feature flags, experiments, surveys. No `query-*` tool covers these; query the `system.*` tables.
- **Multi-event joins or aggregations across event types** that don't fit a single series.
- **Sophisticated queries beyond `query-*` schemas** — custom grouping, window functions, non-trivial CTEs, data warehouse joins.
- **Pre-filtering or shaping** a large dataset before running a `query-*` call.

If a `query-*` tool fits, use it. Default to `query-*`; SQL is the escape hatch, not the starting point.

### Always consult the `querying-posthog-data` skill

Before writing any SQL, read the PostHog `querying-posthog-data` skill. It is the source of truth for up-to-date HogQL patterns, system table schemas (`system.insights`, `system.dashboards`, `system.cohorts`, etc.), and function references. Do not rely on training data — table and column names drift.

### Discovery workflow (mandatory)

1. **Warehouse schema** — call `read-data-warehouse-schema` to verify tables, views, and columns. Do not guess names. For a specific custom warehouse table, inspect its columns with:

   ```sql
   SELECT columns FROM system.data_warehouse_tables WHERE name = 'my_table'
   ```

2. **Event taxonomy** — call `read-data-schema` to verify events, properties, and property values. Do not rely on training data or PostHog defaults.
3. **Write the SQL** only after steps 1 and 2 confirm the data exists, using the verified table and column names.

If the required events, properties, or tables do not exist, say so — do not run queries that will return empty results.

### Handling large results

Large JSON values in results (notably full `properties` objects) are truncated by default. If you anticipate a large result set, or you are selecting the full `properties` object (e.g., `SELECT properties FROM events`), dump the results to a file and process them with bash rather than returning them inline. Alternatively, cherry-pick specific keys (`properties.$browser`) instead of the whole object.

### Large LLM trace fields are stripped from `events.properties`

For LLM events (`$ai_generation`, `$ai_trace`, `$ai_span`, etc.), these specific keys with large values are stripped from `events.properties`:

- `properties.$ai_input`
- `properties.$ai_output`
- `properties.$ai_output_choices`
- `properties.$ai_input_state`
- `properties.$ai_output_state`
- `properties.$ai_tools`

Prefer `query-llm-trace` / `query-llm-traces-list` whenever you need any of those six keys — they contain information on the proper read patterns to a dedicated AI events table which contains these fields. Other AI properties (token counts, costs, model, trace IDs) stay on `events` in all three regimes and are safe to query directly.

### Observability data-plane tables: `logs`, `posthog.trace_spans`, `posthog.metrics`

PostHog ingests OpenTelemetry signals into three ClickHouse-backed tables that are queryable via HogQL. **Note the namespacing asymmetry** — `logs` is registered at the root, while `trace_spans` and `metrics` live under the `posthog.` namespace and must be referenced as such (e.g. `FROM posthog.trace_spans`):

- `logs` — log entries. Common fields: `body` (also exposed as `message`), `severity_text`, `severity_number`, `service_name`, `attributes`, `resource_attributes`, `trace_id`, `span_id`, `timestamp`. Prefer `posthog:query-logs` for filtered list queries; reach for SQL for aggregations across services or joins with `posthog.trace_spans` / `posthog.metrics` by `trace_id`.
- `posthog.trace_spans` — OpenTelemetry spans. Common fields: `trace_id`, `span_id`, `parent_span_id`, `is_root_span`, `name`, `service_name`, `kind` (0-5), `status_code` (0 Unset, 1 OK, 2 Error), `duration_nano`, `timestamp`, `end_time`, `attributes`, `resource_attributes`. Prefer `posthog:query-apm-spans` / `posthog:apm-trace-get` for span listing and full-trace fetches; reach for SQL for joins with `logs` / `posthog.metrics` by `trace_id`, exemplar lookups, or aggregations the typed tools don't expose.
- `posthog.metrics` — OpenTelemetry metric points. Common fields: `metric_name`, `metric_type` (counter/gauge/histogram), `value`, `count`, `histogram_bounds`, `histogram_counts`, `unit`, `service_name`, `trace_id`, `span_id`, `attributes`, `resource_attributes`, `timestamp`. No typed `query-metrics` tool — use SQL. A projection pre-aggregates by `(team_id, time_bucket, toStartOfMinute(timestamp), service_name, metric_name, metric_type, resource_fingerprint)` with `count/sum/min/max(value)`, so per-minute aggregations grouped by those keys are very cheap.

All three share `team_id`, `time_bucket`, `service_name`, `resource_fingerprint`, and where applicable `trace_id` — cross-signal joins are efficient by design. `trace_id` on `posthog.metrics` is the OpenTelemetry exemplar pattern: a metric anomaly can be drilled into via a sample `trace_id` to pull the full trace and correlated logs.

User HogQL queries against `logs`, `posthog.trace_spans`, and `posthog.metrics` are capped at 50 GB read per query to prevent unbounded scans.

Always pass a tight `timestamp` window. Default to the last hour and widen only when justified.

### Example: three-signal correlation via exemplars

<example>
User: `http.server.duration` p95 for checkout spiked between 14:00 and 14:10 — show me a sample slow trace and the logs in that request.
Assistant: I'll locate the spike, pick an exemplar trace_id, then pull the spans and logs in one stitched query.

```sql
WITH exemplar AS (
    SELECT argMax(trace_id, value) AS trace_id
    FROM posthog.metrics
    WHERE service_name = 'checkout'
      AND metric_name = 'http.server.duration'
      AND timestamp >= toDateTime('2026-05-19 14:00:00')
      AND timestamp <  toDateTime('2026-05-19 14:10:00')
      AND trace_id != ''
)
SELECT 'span' AS source, name AS detail, service_name, duration_nano, status_code, timestamp
FROM posthog.trace_spans
WHERE trace_id = (SELECT trace_id FROM exemplar)
UNION ALL
SELECT 'log', body, service_name, NULL, severity_number, timestamp
FROM logs
WHERE trace_id = (SELECT trace_id FROM exemplar)
ORDER BY timestamp
```

<reasoning>
1. `argMax(trace_id, value)` on `posthog.metrics` picks the slowest exemplar for the window — cheap thanks to the per-minute projection.
2. Joining `posthog.trace_spans` and `logs` by the same `trace_id` returns the full request context in one round trip.
3. UNION ALL with a `source` discriminator avoids three separate calls and keeps the timeline interleaved.
4. Note `logs` is root-level while `posthog.trace_spans` and `posthog.metrics` require the namespace prefix.
</reasoning>
</example>

### Example: searching for existing insights

<example>
User: Do we have any insights tracking revenue or payments?
Assistant: I'll search existing insights and dashboards via SQL.
1. Search insights by name: `execute-sql` with `SELECT id, name, short_id, description FROM system.insights WHERE NOT deleted AND (name ILIKE '%revenue%' OR name ILIKE '%payment%') ORDER BY last_modified_at DESC LIMIT 20`
2. If results are sparse, broaden to dashboards: `execute-sql` with `SELECT id, name, description FROM system.dashboards WHERE NOT deleted AND (name ILIKE '%revenue%' OR name ILIKE '%payment%')`
3. Validate promising insights with `insight-retrieve`.
4. Summarize with links.
<reasoning>
1. SQL against `system.*` tables is the fastest way to discover existing entities — no `query-*` tool covers entity search.
2. ILIKE with multiple terms catches naming variants ("Monthly Revenue", "MRR", "Payment Events").
3. `insight-retrieve` confirms the insight's query configuration still matches intent.
</reasoning>
</example>
