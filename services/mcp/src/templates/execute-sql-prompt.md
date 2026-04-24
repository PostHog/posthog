Executes HogQL — PostHog's variant of SQL that supports most of ClickHouse SQL. "HogQL" and "SQL" are used interchangeably.

{guidelines}

### When to use `execute-sql`

**Prefer `query-*` wrappers** (`query-trends`, `query-funnel`, `query-retention`, `query-stickiness`, `query-paths`, `query-lifecycle`, `query-llm-traces-list`) for analytics questions that map to a supported insight type. They produce typed, saveable insights that map cleanly to the visual product.

Reach for `execute-sql` only when a wrapper cannot express the question:

- **Searching or listing existing PostHog entities** — insights, dashboards, cohorts, feature flags, experiments, surveys. No wrapper covers these; query the `system.*` tables.
- **Agentic exploration** — ad-hoc joins, aggregations across multiple event types, or pre-filtering a large dataset before running a wrapper query.
- **Sophisticated queries beyond wrapper schemas** — custom grouping, window functions, non-trivial CTEs, data warehouse joins.

If a wrapper fits, use the wrapper.

### Always consult the `query-examples` skill

Before writing any SQL, read the PostHog `query-examples` skill. It is the source of truth for up-to-date HogQL patterns, system table schemas (`system.insights`, `system.dashboards`, `system.cohorts`, etc.), and function references. Do not rely on training data — table and column names drift.

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

### Example: searching for existing insights

<example>
User: Do we have any insights tracking revenue or payments?
Assistant: I'll search existing insights and dashboards via SQL.
1. Search insights by name: `execute-sql` with `SELECT id, name, short_id, description FROM system.insights WHERE NOT deleted AND (name ILIKE '%revenue%' OR name ILIKE '%payment%') ORDER BY last_modified_at DESC LIMIT 20`
2. If results are sparse, broaden to dashboards: `execute-sql` with `SELECT id, name, description FROM system.dashboards WHERE NOT deleted AND (name ILIKE '%revenue%' OR name ILIKE '%payment%')`
3. Validate promising insights with `insight-retrieve`.
4. Summarize with links.
<reasoning>
1. SQL against `system.*` tables is the fastest way to discover existing entities — no wrapper covers entity search.
2. ILIKE with multiple terms catches naming variants ("Monthly Revenue", "MRR", "Payment Events").
3. `insight-retrieve` confirms the insight's query configuration still matches intent.
</reasoning>
</example>
