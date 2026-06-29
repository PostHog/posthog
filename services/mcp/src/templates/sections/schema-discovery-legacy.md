### Discovery workflow (mandatory)

1. **Warehouse schema** — call `read-data-warehouse-schema` to verify tables, views, and columns. Do not guess names. **This applies to `system.*` tables too** (`system.insights`, `system.dashboards`, `system.cohorts`, …); their column sets differ per entity and drift over time. For a specific custom warehouse table, inspect its columns with:

   ```sql
   SELECT columns FROM system.data_warehouse_tables WHERE name = 'my_table'
   ```

2. **Event taxonomy** — call `read-data-schema` to verify events, properties, and property values. Do not rely on training data or PostHog defaults.
3. **Write the SQL** only after steps 1 and 2 confirm the data exists, using the verified table and column names.

If the required events, properties, or tables do not exist, say so — do not run queries that will return empty results.
