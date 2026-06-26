import { ReadDataWarehouseSchemaSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

import { invokeMcpTool } from './invokeTool'

// Prompt-only flag: gates whether the SQL discovery instructions steer the agent
// through `system.information_schema.*` instead of the `read-data-warehouse-schema`
// tool. It is deliberately NOT attached to this tool's definition — the tool stays
// registered, advertised, and callable regardless of the flag (the flag only changes
// what the prompts tell the agent to use). Rides the same batched evaluation as
// `RENDER_UI_FEATURE_FLAG` (see request-state-resolver.ts).
export const SQL_SCHEMA_DISCOVERY_FEATURE_FLAG = 'mcp-sql-schema-discovery'

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
    name: 'read-data-warehouse-schema',
    schema,
    handler: readDataWarehouseSchemaHandler,
})

export default tool
