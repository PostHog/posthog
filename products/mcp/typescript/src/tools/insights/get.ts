import { InsightGetSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = InsightGetSchema

type Params = z.infer<typeof schema>

export const getHandler = async (context: Context, params: Params) => {
    const { insightId } = params
    const projectId = await context.stateManager.getProjectId()
    const insightResult = await context.api.insights({ projectId }).get({ insightId })
    if (!insightResult.success) {
        throw new Error(`Failed to get insight: ${insightResult.error.message}`)
    }

    const insightWithUrl = {
        ...insightResult.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/insights/${insightResult.data.short_id}`,
    }

    return { content: [{ type: 'text', text: JSON.stringify(insightWithUrl) }] }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'insight-get',
    schema,
    handler: getHandler,
})

export default tool
