import type { z } from 'zod'

import { MemoryCreateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = MemoryCreateSchema
type Params = z.infer<typeof schema>

export const createHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.memories({ projectId }).create({
        data: params,
    })

    if (!result.success) {
        throw new Error(`Failed to create memory: ${result.error.message}`)
    }

    return {
        message: `Memory created successfully with ID: ${result.data.id}`,
        memory: result.data,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'memory-create',
    schema,
    handler: createHandler,
})

export default tool
