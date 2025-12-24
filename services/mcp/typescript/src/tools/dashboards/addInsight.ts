import type { z } from 'zod'

import { DashboardAddInsightSchema } from '@/schema/tool-inputs'
import { resolveInsightId } from '@/tools/insights/utils'
import type { Context, ToolBase } from '@/tools/types'

const schema = DashboardAddInsightSchema

type Params = z.infer<typeof schema>

export const addInsightHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { data } = params
    const projectId = await context.stateManager.getProjectId()

    const numericInsightId = await resolveInsightId(context, data.insightId, projectId)

    const insightResult = await context.api.insights({ projectId }).get({ insightId: data.insightId })

    if (!insightResult.success) {
        throw new Error(`Failed to get insight: ${insightResult.error.message}`)
    }

    const result = await context.api.dashboards({ projectId }).addInsight({
        data: {
            ...data,
            insightId: numericInsightId,
        },
    })

    if (!result.success) {
        throw new Error(`Failed to add insight to dashboard: ${result.error.message}`)
    }

    const resultWithUrls = {
        ...result.data,
        dashboard_url: `${context.api.getProjectBaseUrl(projectId)}/dashboard/${data.dashboardId}`,
        insight_url: `${context.api.getProjectBaseUrl(projectId)}/insights/${insightResult.data.short_id}`,
    }

    return resultWithUrls
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'add-insight-to-dashboard',
    schema,
    handler: addInsightHandler,
})

export default tool
