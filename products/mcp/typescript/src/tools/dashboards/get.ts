import { DashboardGetSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'
import { formatResponse } from '@/integrations/mcp/utils/formatResponse'

const schema = DashboardGetSchema

type Params = z.infer<typeof schema>

export const getHandler = async (context: Context, params: Params) => {
    const { dashboardId } = params
    const projectId = await context.stateManager.getProjectId()
    const dashboardResult = await context.api.dashboards({ projectId }).get({ dashboardId })

    if (!dashboardResult.success) {
        throw new Error(`Failed to get dashboard: ${dashboardResult.error.message}`)
    }

    return { content: [{ type: 'text', text: formatResponse(dashboardResult.data) }] }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'dashboard-get',
    schema,
    handler: getHandler,
})

export default tool
