

import { DashboardGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'
import { formatResponse } from '@/integrations/mcp/utils/formatResponse'

const schema = DashboardGetAllSchema

type Params = z.infer<typeof schema>

export const getAllHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { data } = params
    const projectId = await context.stateManager.getProjectId()
    const dashboardsResult = await context.api.dashboards({ projectId }).list({ params: data ?? {} })

    if (!dashboardsResult.success) {
        throw new Error(`Failed to get dashboards: ${dashboardsResult.error.message}`)
    }

    return { content: [{ type: 'text', text: formatResponse(dashboardsResult.data) }] }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'dashboards-get-all',
    schema,
    handler: getAllHandler,
})

export default tool
