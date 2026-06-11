import type { z } from 'zod'

import { MemorySchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

import { invokeMcpTool } from './invokeTool'

const schema = MemorySchema

type Params = z.infer<typeof schema>

export const memoryHandler: ToolBase<typeof schema, string>['handler'] = async (
    context: Context,
    params: Params
) => {
    // The backend `manage_memories` tool validates against a `{ args: <action> }` wrapper,
    // so nest the operation under `args` before handing it to the invoke endpoint.
    const result = await invokeMcpTool(context, 'manage_memories', { args: params.operation })

    if (!result.success) {
        throw new Error(result.content)
    }

    return result.content
}

const tool = (): ToolBase<typeof schema, string> => ({
    name: 'memory',
    schema,
    handler: memoryHandler,
})

export default tool
