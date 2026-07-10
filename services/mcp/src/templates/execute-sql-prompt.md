Executes HogQL — PostHog's variant of SQL that supports most of ClickHouse SQL. "HogQL" and "SQL" are used interchangeably.

Count unique users with `uniqExact(person_id)` or `count(DISTINCT person_id)`, never `distinct_id` — one person can have many distinct IDs, so counting distinct IDs overcounts users. Use `distinct_id` only for a deliberate raw-visitor count.

{guidelines}

### When to use `execute-sql`

**Use `query-*` tools whenever the question maps to a supported insight type.** These tools produce typed, saveable insights; SQL forfeits that.
Reach for `execute-sql` only when no `query-*` tool can express the question:

- **Searching or listing existing PostHog entities** — insights, dashboards, cohorts, feature flags, experiments, surveys. No `query-*` tool covers these; query the `system.*` tables.
- **Multi-event joins or aggregations across event types** that don't fit a single series.
- **Sophisticated queries beyond `query-*` schemas** — custom grouping, window functions, non-trivial CTEs, data warehouse joins.
- **Pre-filtering or shaping** a large dataset before running a `query-*` call.

If a `query-*` tool fits, use it. Default to `query-*`; SQL is the escape hatch, not the starting point.

{schema_discovery}

### Format SQL for readability

Write SQL a human can scan: multi-line with indentation, one column/CTE per line, and inline `--` comments for non-obvious logic. This matters most for queries you save via `view-create` / `view-update` — the SQL editor stores and renders the string verbatim, so a minified one-liner stays unreadable for whoever opens the view later.

### Handling large results

Large JSON values in results (notably full `properties` objects) are truncated by default. If you anticipate a large result set, or you are selecting the full `properties` object (e.g., `SELECT properties FROM events`), dump the results to a file and process them with bash rather than returning them inline. Alternatively, cherry-pick specific keys (`properties.$browser`) instead of the whole object.

### Large LLM trace fields live on the `posthog.ai_events` table, not `events.properties`

For LLM events (`$ai_generation`, `$ai_trace`, `$ai_span`, etc.) the heavy keys are **not stored on `events.properties`** — they live as native columns on a dedicated ClickHouse table. Like `posthog.trace_spans` / `posthog.metrics`, reference it as `posthog.ai_events` (a bare `FROM ai_events` errors with "Unknown table"):

| `events` property    | `ai_events` column |
| -------------------- | ------------------ |
| `$ai_input`          | `input`            |
| `$ai_output`         | `output`           |
| `$ai_output_choices` | `output_choices`   |
| `$ai_input_state`    | `input_state`      |
| `$ai_output_state`   | `output_state`     |
| `$ai_tools`          | `tools`            |

Other AI properties (token counts, costs, model, `$ai_trace_id`) stay on `events` in all regimes and are safe to query there.

`posthog.ai_events` is `ORDER BY (team_id, trace_id, timestamp)`, so **anchor on `trace_id`, never scan by `timestamp`**. Rows are dropped after the retention period (30 days by default), so older traces have no content. Nothing restricts which heavy columns an event can carry, but the typical shape is: `$ai_generation` carries `input` / `output_choices` / `tools` (embeddings carry `input`); `$ai_span` and `$ai_trace` carry `input_state` / `output_state`.

- **Single trace** — `SELECT input, output_choices FROM posthog.ai_events WHERE trace_id = '<id>' ORDER BY timestamp`.
- **Batch / analytics** — filter the timestamp-indexed `events` table first to get the trace IDs, then fetch heavy content from `posthog.ai_events` anchored on `trace_id`:

  ```sql
  WITH matching_traces AS (
      SELECT DISTINCT properties.$ai_trace_id AS trace_id
      FROM events
      WHERE event = '$ai_generation'
        AND timestamp >= now() - INTERVAL 7 DAY
        AND properties.$ai_model = 'gpt-4o'
  )
  SELECT a.trace_id, a.span_id, a.model, a.input, a.output_choices
  FROM posthog.ai_events AS a
  WHERE a.trace_id IN (SELECT trace_id FROM matching_traces)
  ORDER BY a.trace_id, a.timestamp
  ```

The `query-llm-trace` / `query-llm-traces-list` tools read `posthog.ai_events` for you; prefer them when a single trace's content is all you need.

### Observability data-plane tables: `logs`, `posthog.trace_spans`, `posthog.metrics`

PostHog ingests OpenTelemetry signals into three ClickHouse-backed tables that are queryable via HogQL. **Note the namespacing asymmetry** — `logs` is registered at the root, while `trace_spans` and `metrics` live under the `posthog.` namespace and must be referenced as such (e.g. `FROM posthog.trace_spans`):

- `logs` — log entries. Common fields: `body` (also exposed as `message`), `severity_text`, `severity_number`, `service_name`, `attributes`, `resource_attributes`, `trace_id`, `span_id`, `timestamp`. Prefer `posthog:query-logs` for filtered list queries; reach for SQL for aggregations across services or joins with `posthog.trace_spans` / `posthog.metrics` by `trace_id`.
- `posthog.trace_spans` — OpenTelemetry spans. Common fields: `trace_id`, `span_id`, `parent_span_id`, `is_root_span`, `name`, `service_name`, `kind` (0-5), `status_code` (0 Unset, 1 OK, 2 Error), `duration_nano`, `timestamp`, `end_time`, `attributes`, `resource_attributes`. Prefer `posthog:query-apm-spans` / `posthog:apm-trace-get` for span listing and full-trace fetches; reach for SQL for joins with `logs` / `posthog.metrics` by `trace_id`, exemplar lookups, or aggregations the typed tools don't expose.
- `posthog.metrics` — OpenTelemetry metric points. Common fields: `metric_name`, `metric_type` (counter/gauge/histogram), `value`, `count`, `histogram_bounds`, `histogram_counts`, `unit`, `aggregation_temporality` (`delta` or `cumulative`), `is_monotonic`, `service_name`, `trace_id`, `span_id`, `attributes`, `resource_attributes`, `timestamp`. No typed `query-metrics` tool — use SQL. A projection pre-aggregates by `(team_id, time_bucket, toStartOfMinute(timestamp), service_name, metric_name, metric_type, resource_fingerprint)` with `count/sum/min/max(value)`, so per-minute aggregations grouped by those keys are very cheap. **Important for counters:** check `aggregation_temporality` before aggregating — `SUM(value)` over a window is only correct for `delta`. For `cumulative` counters, the value is a running total, so use `argMax(value, timestamp)` (or `max(value) - min(value)` for a rate) to avoid double-counting. Always filter or split by `aggregation_temporality` when both regimes can appear for a given `metric_name`.

All three share `team_id`, `time_bucket`, `service_name`, `resource_fingerprint`, and where applicable `trace_id`. `trace_id` on `posthog.metrics` is the OpenTelemetry exemplar pattern — a metric anomaly can be drilled into via a sample `trace_id` to pull the full trace and correlated logs. **Note:** exemplar extraction is not yet wired up in the ingestion pipeline (the `_exemplars` argument is unused in `rust/capture-logs/src/metric_record.rs`), so `posthog.metrics.trace_id` is always empty today. The pattern below describes the intended capability; the "works today" alternative anchors on `posthog.trace_spans` instead.

**`trace_id` format:** Both `logs` and `posthog.trace_spans` store `trace_id` as a 24-character base64-encoded 16-byte value (e.g. hex `21EDB3A025A9ECD32ADF3E5D7548A4F4` encodes to `Ie2zoCWp7NMq3z5ddUik9A==`). The MCP API layer converts to hex via `hex(tryBase64Decode(trace_id))` for display. Raw HogQL queries see the base64 form. Unset = `'AAAAAAAAAAAAAAAAAAAAAA=='`. `posthog.metrics.trace_id` is a plain string, empty when unset (once exemplars land it will match the base64 format of the other two tables). Joins are direct equality on `trace_id`.

User HogQL queries against `logs`, `posthog.trace_spans`, and `posthog.metrics` are capped at 50 GB read per query to prevent unbounded scans.

Always pass a tight `timestamp` window. Default to the last hour and widen only when justified.

### Example: three-signal correlation (works today, span-anchored)

<example>
User: An error spike on `checkout` over the last hour — show me a sample slow error trace and the logs in that request.
Assistant: I'll pick the slowest error root span as the anchor, then pull the spans and logs in one stitched query.

```sql
WITH anchor AS (
    SELECT trace_id
    FROM posthog.trace_spans
    WHERE service_name = 'checkout'
      AND is_root_span
      AND status_code = 2
      AND timestamp >= now() - INTERVAL 1 HOUR
    ORDER BY duration_nano DESC
    LIMIT 1
)
SELECT 'span' AS source, name AS detail, service_name, duration_nano, status_code, NULL AS severity_number, timestamp
FROM posthog.trace_spans
WHERE trace_id = (SELECT trace_id FROM anchor)
  AND timestamp >= now() - INTERVAL 1 HOUR
UNION ALL
SELECT 'log', body, service_name, NULL, NULL, severity_number, timestamp
FROM logs
WHERE trace_id = (SELECT trace_id FROM anchor)
  AND timestamp >= now() - INTERVAL 1 HOUR
ORDER BY timestamp
```

<reasoning>
- Anchoring on `posthog.trace_spans` works today because spans always carry a populated `trace_id`. Once `posthog.metrics` exemplars land, the CTE can be swapped for `argMax(trace_id, value) FROM posthog.metrics WHERE … AND trace_id != ''` to drill from a metric spike instead.
- `trace_id` is stored as base64 in both `logs` and `posthog.trace_spans`, so direct equality works — no decoding needed.
- `UNION ALL` with a `source` discriminator avoids three separate calls and keeps the timeline interleaved.
- Note `logs` is root-level while `posthog.trace_spans` and `posthog.metrics` require the namespace prefix.
- The inner `WHERE` clauses repeat the time window so the optimizer keeps both legs of the UNION efficient.
</reasoning>
</example>

### Example: searching for existing insights

<example>
User: Do we have any insights tracking revenue or payments?
Assistant: I'll search existing insights and dashboards via SQL.
1. Discover columns: run the schema-discovery step from the workflow above to confirm which columns each table exposes before projecting or ordering by them. Column sets differ per system table — e.g. `system.insights` has `short_id` and `last_modified_at`, but `system.dashboards` has neither (its only timestamp is `created_at`). Without this step I'd be guessing.
2. Search insights by name (using only confirmed columns): `execute-sql` with `SELECT id, name, short_id, description FROM system.insights WHERE NOT deleted AND (name ILIKE '%revenue%' OR name ILIKE '%payment%') ORDER BY last_modified_at DESC LIMIT 20`.
3. If results are sparse, broaden to dashboards (re-using the same schema lookup — `system.dashboards` has its own column set, e.g. no `short_id` and no `last_modified_at`): `execute-sql` with `SELECT id, name, description FROM system.dashboards WHERE NOT deleted AND (name ILIKE '%revenue%' OR name ILIKE '%payment%') ORDER BY created_at DESC LIMIT 20`.
4. Validate promising insights with `insight-retrieve`.
5. Summarize with links.
<reasoning>
1. Schema discovery is mandatory step 1 of the discovery workflow above; `system.*` tables' column sets differ per entity (e.g. `system.dashboards` has no `last_modified_at` or `short_id` — ordering it by `last_modified_at` fails field resolution).
2. SQL against `system.*` tables is the fastest way to discover existing entities — no `query-*` tool covers entity search.
3. ILIKE with multiple terms catches naming variants ("Monthly Revenue", "MRR", "Payment Events").
4. `insight-retrieve` confirms the insight's query configuration still matches intent.
</reasoning>
</example>
