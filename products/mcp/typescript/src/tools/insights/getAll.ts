import { InsightGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = InsightGetAllSchema

type Params = z.infer<typeof schema>

export const getAllHandler = async (context: Context, params: Params) => {
    const { data } = params
    const projectId = await context.stateManager.getProjectId()
    const insightsResult = await context.api.insights({ projectId }).list({ params: { ...data } })

    if (!insightsResult.success) {
        throw new Error(`Failed to get insights: ${insightsResult.error.message}`)
    }

    const insightsWithUrls = insightsResult.data.map((insight) => ({
        ...insight,
        url: `${context.api.getProjectBaseUrl(projectId)}/insights/${insight.short_id}`,
    }))

    return { content: [{ type: 'text', text: JSON.stringify(insightsWithUrls) }] }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'insights-get-all',
    schema,
    handler: getAllHandler,
})

export default tool
