import { InsightUpdateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'
import { resolveInsightId } from './utils'

const schema = InsightUpdateSchema

type Params = z.infer<typeof schema>

export const updateHandler = async (context: Context, params: Params) => {
    const { insightId, data } = params
    const projectId = await context.stateManager.getProjectId()

    const numericId = await resolveInsightId(context, insightId, projectId)

    const insightResult = await context.api.insights({ projectId }).update({
        insightId: numericId,
        data,
    })

    if (!insightResult.success) {
        throw new Error(`Failed to update insight: ${insightResult.error.message}`)
    }

    const insightWithUrl = {
        ...insightResult.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/insights/${insightResult.data.short_id}`,
    }

    return { content: [{ type: 'text', text: JSON.stringify(insightWithUrl) }] }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'insight-update',
    schema,
    handler: updateHandler,
})

export default tool
