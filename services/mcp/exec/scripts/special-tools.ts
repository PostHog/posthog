/**
 * Special "tools" that aren't OpenAPI operations but should appear as `Client` methods.
 *
 * Two groups:
 *
 * 1. mcp_tools/* — backend tools registered via `mcp_tool_registry` and exposed at
 *    POST /api/environments/{project_id}/mcp_tools/{name}/. Source of truth:
 *    `products/posthog_ai/backend/api/mcp_tools.py` (the viewset) and
 *    `ee/hogai/tools/{tool}/mcp_tool.py` (each tool's pydantic input + handler).
 *    The v2 MCP wraps these as named tools in `services/mcp/src/tools/posthogAiTools/`.
 *
 * 2. Query wrappers — POST to /api/environments/{project_id}/query/ with a typed
 *    `Assistant*Query` body. The list comes from the YAML (loaded separately).
 *
 * For (1) we hand-list because the inputs are pydantic, not OpenAPI, and the v2 codegen
 * wires them up via hand-written Zod in `services/mcp/src/schema/tool-inputs.ts`.
 */

export interface SpecialMethod {
    /** TypeScript method name on `Client` (camelCase). */
    methodName: string
    /** v2 MCP tool name (kebab-case). Used to populate the search index id. */
    toolName: string
    /** Backend tool name passed in the URL path. */
    backendName: string
    /** One-line summary for the search index. */
    summary: string
    /** Full JSDoc / description shown by the `read` tool. May be markdown. */
    description: string
    /** TypeScript input interface declaration emitted alongside the method (or `null` if no input). */
    inputDecl: string | null
    /** Name of the input interface (must match `inputDecl`'s `export interface NAME { ... }`). */
    inputName: string | null
    /** TypeScript return type. */
    responseType: string
}

const EXECUTE_SQL_DESCRIPTION = `Executes HogQL — PostHog's variant of SQL that supports most of ClickHouse SQL.

Prefer the typed query wrappers (\`client.queryTrends\`, \`client.queryFunnel\`, \`client.queryRetention\`, \`client.queryStickiness\`, \`client.queryPaths\`, \`client.queryLifecycle\`, \`client.queryLlmTracesList\`) when the question maps to a supported insight type — they produce typed, saveable insights.

Reach for \`executeSql\` when a wrapper cannot express the question:
- Searching or listing existing PostHog entities (insights, dashboards, cohorts, flags, experiments, surveys) — query the \`system.*\` tables.
- Agentic exploration — ad-hoc joins, aggregations across multiple event types, pre-filtering before running a wrapper query.
- Custom grouping, window functions, non-trivial CTEs, data warehouse joins.

Discovery workflow (mandatory):
1. Verify warehouse tables/columns first via \`client.readDataWarehouseSchema()\`.
2. Verify events/properties via \`client.readDataSchema({ query: { kind: 'events' } })\` etc.
3. Only write SQL once 1 and 2 confirm the data exists.

Large JSON values (notably full \`properties\`) are truncated by default. Set \`truncate: false\` only when you need full untruncated results (e.g. dumping to a file). For large result sets, cherry-pick specific keys (\`properties.$browser\`) instead of the whole object.

Returns a string — the formatted query result.`

const READ_DATA_SCHEMA_DESCRIPTION = `Inspects the PostHog event taxonomy. Use to discover what events exist and what properties they carry before writing a HogQL query or wrapper call.

The \`query.kind\` discriminator selects the lookup:
- \`events\` — list known event definitions for the project (paginated via limit/offset).
- \`event_properties\` — list properties recorded for a given event name.
- \`entity_properties\` — list properties for an entity (\`person\`, \`session\`, or \`group/<index>\`).
- \`action_properties\` — list properties recorded for a given action id.
- \`event_property_values\` — sample distinct values for a property on a given event.
- \`entity_property_values\` — sample distinct values for a property on an entity.
- \`action_property_values\` — sample distinct values for a property on an action.

Returns a string — the formatted taxonomy answer.`

const READ_DATA_WAREHOUSE_SCHEMA_DESCRIPTION = `Returns core data-warehouse schemas (table names, columns, types) for the project. No input needed.

Call this before writing HogQL that joins or selects from data-warehouse tables. Custom warehouse tables can be inspected in detail via:

\`\`\`sql
SELECT columns FROM system.data_warehouse_tables WHERE name = 'my_table'
\`\`\`

Returns a string — the formatted schema listing.`

export const SPECIAL_CLIENT_METHODS: SpecialMethod[] = [
    {
        methodName: 'executeSql',
        toolName: 'execute-sql',
        backendName: 'execute_sql',
        summary: 'Execute a HogQL SQL query',
        description: EXECUTE_SQL_DESCRIPTION,
        inputName: 'ExecuteSqlInput',
        inputDecl: `export interface ExecuteSqlInput {
    /** The final SQL query to be executed. */
    query: string
    /** Whether to truncate large blob/JSON values in results. Defaults to true. Set to false when you need full untruncated results (e.g., for dumping to a file). */
    truncate?: boolean
}`,
        responseType: 'string',
    },
    {
        methodName: 'readDataSchema',
        toolName: 'read-data-schema',
        backendName: 'read_taxonomy',
        summary: 'Read PostHog event/property taxonomy',
        description: READ_DATA_SCHEMA_DESCRIPTION,
        inputName: 'ReadDataSchemaInput',
        inputDecl: `export type ReadDataSchemaQuery =
    | { kind: 'events'; limit?: number; offset?: number }
    | { kind: 'event_properties'; event_name: string }
    | { kind: 'entity_properties'; entity: string }
    | { kind: 'action_properties'; action_id: number }
    | { kind: 'entity_property_values'; entity: string; property_name: string }
    | { kind: 'event_property_values'; event_name: string; property_name: string }
    | { kind: 'action_property_values'; action_id: number; property_name: string }

export interface ReadDataSchemaInput {
    query: ReadDataSchemaQuery
}`,
        responseType: 'string',
    },
    {
        methodName: 'readDataWarehouseSchema',
        toolName: 'read-data-warehouse-schema',
        backendName: 'read_data_warehouse_schema',
        summary: 'Read data-warehouse table schemas',
        description: READ_DATA_WAREHOUSE_SCHEMA_DESCRIPTION,
        inputName: null,
        inputDecl: null,
        responseType: 'string',
    },
]
