import type { z } from 'zod'

import { MemoryUpdateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = MemoryUpdateSchema
type Params = z.infer<typeof schema>

export const updateHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.memories({ projectId }).update({
        memoryId: params.memoryId,
        data: params.data,
    })

    if (!result.success) {
        throw new Error(`Failed to update memory: ${result.error.message}`)
    }

    return {
        message: `Memory ${params.memoryId} updated successfully.`,
        memory: result.data,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'memory-update',
    schema,
    handler: updateHandler,
})

export default tool
