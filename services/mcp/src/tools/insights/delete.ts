import type { z } from 'zod'

import { InsightDeleteSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

import { resolveInsightId } from './utils'

const schema = InsightDeleteSchema

type Params = z.infer<typeof schema>

export const deleteHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { insightId } = params
    const projectId = await context.stateManager.getProjectId()

    const numericId = await resolveInsightId(context, insightId, projectId)
    const result = await context.api.insights({ projectId }).delete({ insightId: numericId })

    if (!result.success) {
        throw new Error(`Failed to delete insight: ${result.error.message}`)
    }

    return result.data
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'insight-delete',
    schema,
    handler: deleteHandler,
})

export default tool
