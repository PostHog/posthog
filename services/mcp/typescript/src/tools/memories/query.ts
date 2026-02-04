import type { z } from 'zod'

import { MemoryQuerySchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = MemoryQuerySchema
type Params = z.infer<typeof schema>

export const queryHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.memories({ projectId }).query({
        data: params,
    })

    if (!result.success) {
        throw new Error(`Failed to query memories: ${result.error.message}`)
    }

    const { results, count } = result.data

    if (count === 0) {
        return {
            message: 'No memories found matching your query.',
            results: [],
            count: 0,
        }
    }

    return {
        message: `Found ${count} relevant memories.`,
        results,
        count,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'memory-query',
    schema,
    handler: queryHandler,
})

export default tool
