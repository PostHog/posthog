import type { z } from 'zod'

import { MaxReadDataSchemaSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

import { invokeMaxTool } from './invokeMaxTool'

const schema = MaxReadDataSchemaSchema

type Params = z.infer<typeof schema>

export const readDataSchemaHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const result = await invokeMaxTool(context, 'read_taxonomy', {
        query: params.query,
    })

    if (!result.success) {
        throw new Error(result.content)
    }

    return {
        content: result.content,
        data: result.data,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'read-data-schema',
    schema,
    handler: readDataSchemaHandler,
})

export default tool
