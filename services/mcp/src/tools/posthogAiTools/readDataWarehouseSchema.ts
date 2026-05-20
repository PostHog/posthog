import { z } from 'zod'

import { ReadDataWarehouseSchemaSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

import { invokeMcpTool } from './invokeTool'

const schema = ReadDataWarehouseSchemaSchema

type Params = z.infer<typeof schema>

export const readDataWarehouseSchemaHandler: ToolBase<typeof schema, string>['handler'] = async (
    context: Context,
    params: Params
) => {
    const query: Record<string, unknown> = { kind: 'data_warehouse_schema' }
    if (params?.table_names && params.table_names.length > 0) {
        query.table_names = params.table_names
    }
    if (params?.include && params.include.length > 0) {
        query.include = params.include
    }

    const result = await invokeMcpTool(context, 'read_data_warehouse_schema', { query })

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
