### Discovery workflow (mandatory)

1. **Table & column schema** — discover the data model with HogQL against `system.information_schema.*`. Do not guess table or column names; they differ per entity and drift over time.
   - List available tables: `SELECT table_name, table_type, description FROM system.information_schema.tables`.
   - Inspect a table's columns: `SELECT column_name, data_type, is_nullable, description FROM system.information_schema.columns WHERE table_name = 'events'`.
   - Discover joins / foreign keys: `SELECT source_table, source_column, target_table, target_column FROM system.information_schema.relationships WHERE source_table = 'events'`.

   **This covers `system.*` entity tables too** (`system.insights`, `system.dashboards`, `system.cohorts`, …) — query them by their full name, e.g. `WHERE table_name = 'system.insights'`. Their column sets differ per entity, so confirm columns before projecting them.
2. **Event taxonomy** — call `read-data-schema` to verify events, properties, and property values. Do not rely on training data or PostHog defaults.
3. **Write the SQL** only after steps 1 and 2 confirm the data exists, using the verified table and column names.

If the required events, properties, or tables do not exist, say so — do not run queries that will return empty results.
