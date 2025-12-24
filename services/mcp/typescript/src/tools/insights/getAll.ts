import type { z } from 'zod'

import { InsightGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = InsightGetAllSchema

type Params = z.infer<typeof schema>

export const getAllHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
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

    return insightsWithUrls
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'insights-get-all',
    schema,
    handler: getAllHandler,
})

export default tool
