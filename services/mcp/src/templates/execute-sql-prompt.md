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

1. **Warehouse schema** — call `read-data-warehouse-schema` to verify tables, views, and columns. Do not guess names. **This applies to `system.*` tables too** (`system.insights`, `system.dashboards`, `system.cohorts`, …); their column sets differ per entity and drift over time. For a specific custom warehouse table, inspect its columns with:

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

### Example: searching for existing insights

<example>
User: Do we have any insights tracking revenue or payments?
Assistant: I'll search existing insights and dashboards via SQL.
1. Discover columns: `read-data-warehouse-schema` to confirm `system.insights` and `system.dashboards` expose `name`, `description`, `deleted`, `last_modified_at`, and the ID columns I plan to project. Without this step I'd be guessing — column sets differ per system table.
2. Search insights by name (using only confirmed columns): `execute-sql` with `SELECT id, name, short_id, description FROM system.insights WHERE NOT deleted AND (name ILIKE '%revenue%' OR name ILIKE '%payment%') ORDER BY last_modified_at DESC LIMIT 20`.
3. If results are sparse, broaden to dashboards (re-using the same schema lookup — `system.dashboards` has its own column set, e.g. no `short_id`): `execute-sql` with `SELECT id, name, description FROM system.dashboards WHERE NOT deleted AND (name ILIKE '%revenue%' OR name ILIKE '%payment%') ORDER BY last_modified_at DESC LIMIT 20`.
4. Validate promising insights with `insight-retrieve`.
5. Summarize with links.
<reasoning>
1. `read-data-warehouse-schema` is mandatory step 1 of the discovery workflow above; `system.*` tables are warehouse tables and their column sets differ per entity (e.g. not every system table has `last_modified_at` or `short_id`).
2. SQL against `system.*` tables is the fastest way to discover existing entities — no `query-*` tool covers entity search.
3. ILIKE with multiple terms catches naming variants ("Monthly Revenue", "MRR", "Payment Events").
4. `insight-retrieve` confirms the insight's query configuration still matches intent.
</reasoning>
</example>
