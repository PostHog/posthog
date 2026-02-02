import type { z } from 'zod'

import { MemoryDeleteSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = MemoryDeleteSchema
type Params = z.infer<typeof schema>

export const deleteHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.memories({ projectId }).delete({
        memoryId: params.memoryId,
    })

    if (!result.success) {
        throw new Error(`Failed to delete memory: ${result.error.message}`)
    }

    return {
        message: `Memory ${params.memoryId} deleted successfully.`,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'memory-delete',
    schema,
    handler: deleteHandler,
})

export default tool
