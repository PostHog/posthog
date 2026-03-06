import { ReadDataWarehouseSchemaSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

import { invokeMcpTool } from './invokeTool'

const schema = ReadDataWarehouseSchemaSchema

export const readDataWarehouseSchemaHandler: ToolBase<typeof schema>['handler'] = async (context: Context) => {
    const result = await invokeMcpTool(context, 'read_data_warehouse_schema', {
        query: { kind: 'data_warehouse_schema' },
    })

    if (!result.success) {
        throw new Error(result.content)
    }

    return result.content
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'read-data-warehouse-schema',
    schema,
    handler: readDataWarehouseSchemaHandler,
})

export default tool
