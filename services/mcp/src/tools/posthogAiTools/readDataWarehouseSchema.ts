import { ReadDataWarehouseSchemaSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

import { invokeMcpTool } from './invokeTool'

// Flag that routes schema discovery through `system.information_schema.*` SQL. When it
// is on, two things happen: the discovery instructions steer the agent toward
// `execute-sql` against `system.information_schema.*`, and this tool is gated OUT of the
// catalog (via `feature_flag_behavior: "disable"` in tool-definitions.json) so the SQL
// path is the only one. An agent that still calls it by name gets the redirect in
// `DEPRECATED_TOOL_REDIRECTS`. Off-flag, the tool stays registered and callable.
//
// TODO: once `mcp-sql-schema-discovery` is rolled out to 100%, delete this tool
// entirely — the `system.information_schema.*` SQL path fully replaces it — and retire
// this flag along with the legacy (non-infoschema) discovery prompt sections.
export const SQL_SCHEMA_DISCOVERY_FEATURE_FLAG = 'mcp-sql-schema-discovery'

// The advertised name of this tool.
export const READ_DATA_WAREHOUSE_SCHEMA_TOOL_NAME = 'read-data-warehouse-schema'

const schema = ReadDataWarehouseSchemaSchema

export const readDataWarehouseSchemaHandler: ToolBase<typeof schema, string>['handler'] = async (context: Context) => {
    const result = await invokeMcpTool(context, 'read_data_warehouse_schema', {
        query: { kind: 'data_warehouse_schema' },
    })

    if (!result.success) {
        throw new Error(result.content)
    }

    return result.content
}

const tool = (): ToolBase<typeof schema, string> => ({
    name: READ_DATA_WAREHOUSE_SCHEMA_TOOL_NAME,
    schema,
    handler: readDataWarehouseSchemaHandler,
})

export default tool
