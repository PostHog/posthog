Executes HogQL — PostHog's variant of SQL that supports most of ClickHouse SQL. "HogQL" and "SQL" are used interchangeably.

### When to use `execute-sql`

Use SQL for record inspection, custom calculations, joins, existing SQL, or requests for SQL. SQL results can inform how you construct a later typed query. Typed query tools cannot accept SQL results as input. SQL cases include:

- **Searching or listing existing PostHog entities** — insights, dashboards, cohorts, feature flags, experiments, surveys. No typed query tool covers these; query the `system.*` tables.
- **Multi-event joins or aggregations across event types** that do not fit a single series.
- **Sophisticated queries beyond typed query schemas** — custom grouping, window functions, non-trivial CTEs, data warehouse joins.

For governed measures, check for a matching approved metric before deriving a new calculation.

Default to typed runners for new product analytics and dashboard insights whenever their schemas support the requested calculation, including simple event counts, unique users, property sums, breakdowns, and time series (`query-trends`). Use the matching typed runner for funnels, retention, stickiness, paths, and lifecycle; do not approximate their standard calculation rules with SQL.

When both methods fit, use the typed runner. SQL familiarity, SQL examples, or an earlier SQL discovery call do not justify SQL for the final analysis. Use SQL directly for the SQL-specific tasks above, without requiring a failed typed-query attempt. Keep valid existing SQL when it fits the task, and reassess when the task changes.

Both typed queries and SQL support visualizations. Save supported dashboard analyses as native query nodes. A chart or table request, or a harness needing a separate rendering call, does not justify SQL.

{hogql}

{schema_discovery}

### Common pitfalls

- **For `system.*` entities, `information_schema` stores the fully-qualified `table_name`:** `table_name = 'system.insights'` works alone. The bare name works only with a schema filter: `table_schema = 'system' AND table_name = 'insights'`. A bare `table_name = 'insights'` alone returns zero rows.
- **HogQL rejects the ClickHouse `SETTINGS` clause outright** — appending `SETTINGS ...` (e.g. to tune `max_execution_time` or `join_algorithm`) always fails with `Unsupported: SelectStmt.settingsClause()`. Don't include it.
- **`toDate()` takes exactly one argument** — it does not accept ClickHouse's `toDate(value, timezone)` form. Convert timezone first with `toTimeZone()`, then wrap in `toDate()`: `toDate(toTimeZone(timestamp, 'US/Pacific'))`, not `toDate(timestamp, 'US/Pacific')`.
- **Width-suffixed conversion functions aren't supported** — `toInt64`, `toInt32`, `toFloat64`, `toUInt8`, etc. (and their `OrNull`/`OrZero` variants) always fail. Use the unsuffixed form instead: `toInt()`, `toFloat()`, `toUInt()`, `toIntOrNull()`, `toFloatOrZero()`, and so on.

### Format SQL for readability

Write SQL a human can scan: multi-line with indentation, one column/CTE per line, and inline `--` comments for non-obvious logic. This matters most for queries you save via `view-create` / `view-update` — the SQL editor stores and renders the string verbatim, so a minified one-liner stays unreadable for whoever opens the view later.

### Handling large results

Large JSON values in results (notably full `properties` objects) are truncated by default. If you anticipate a large result set, or you are selecting the full `properties` object (e.g., `SELECT properties FROM events`), dump the results to a file and process them with bash rather than returning them inline. Alternatively, cherry-pick specific keys (`properties.$browser`) instead of the whole object.

{reference}
