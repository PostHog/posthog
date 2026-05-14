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

1. **Schema** — query the catalog system tables to verify tables, columns, and joins. Do not guess names.
   - List tables in scope (warehouse tables, saved-query views, system tables, core PostHog tables) with their semantic role and business domain: `SELECT id, kind, name, description, semantic_role, business_domain, tags FROM system.tables WHERE name ILIKE '%order%' LIMIT 50`
   - Inspect a table's columns (types, nullability, semantic type, PII class, descriptions): `SELECT name, position, clickhouse_type, hogql_type, nullable, semantic_type, pii_class, description FROM system.columns WHERE node_id = '<table id from system.tables>' ORDER BY position`
   - Find joins, foreign keys, or lineage between tables before writing a multi-table query: `SELECT source_node_id, source_column_id, target_node_id, target_column_id, kind, confidence, status FROM system.relationships WHERE source_node_id IN (<ids>) OR target_node_id IN (<ids>)`
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
