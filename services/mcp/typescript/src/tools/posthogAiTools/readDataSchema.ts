import type { z } from 'zod'

import { ReadDataSchemaSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

import { invokeMcpTool } from './invokeTool'

const schema = ReadDataSchemaSchema

type Params = z.infer<typeof schema>

export const readDataSchemaHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const result = await invokeMcpTool(context, 'read_taxonomy', {
        query: params.query,
    })

    if (!result.success) {
        throw new Error(result.content)
    }

    return result.content
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'read-data-schema',
    schema,
    handler: readDataSchemaHandler,
})

export default tool
