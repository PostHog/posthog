

import { DashboardUpdateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'
import { formatResponse } from '@/integrations/mcp/utils/formatResponse'

const schema = DashboardUpdateSchema

type Params = z.infer<typeof schema>

export const updateHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { dashboardId, data } = params
    const projectId = await context.stateManager.getProjectId()
    const dashboardResult = await context.api.dashboards({ projectId }).update({ dashboardId, data })

    if (!dashboardResult.success) {
        throw new Error(`Failed to update dashboard: ${dashboardResult.error.message}`)
    }

    const dashboardWithUrl = {
        ...dashboardResult.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/dashboard/${dashboardResult.data.id}`,
    }

    return { content: [{ type: 'text', text: formatResponse(dashboardWithUrl) }] }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'dashboard-update',
    schema,
    handler: updateHandler,
})

export default tool
