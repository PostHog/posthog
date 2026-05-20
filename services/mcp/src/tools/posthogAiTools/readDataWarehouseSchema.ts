import type { z } from 'zod'

import { ReadDataWarehouseSchemaSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

import { invokeMcpTool } from './invokeTool'

const schema = ReadDataWarehouseSchemaSchema

type Params = z.infer<typeof schema>

export const readDataWarehouseSchemaHandler: ToolBase<typeof schema, string>['handler'] = async (
    context: Context,
    { query }: Params
) => {
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
