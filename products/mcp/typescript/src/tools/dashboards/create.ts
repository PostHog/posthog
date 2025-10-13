import { DashboardCreateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = DashboardCreateSchema

type Params = z.infer<typeof schema>

export const createHandler = async (context: Context, params: Params) => {
    const { data } = params
    const projectId = await context.stateManager.getProjectId()
    const dashboardResult = await context.api.dashboards({ projectId }).create({ data })

    if (!dashboardResult.success) {
        throw new Error(`Failed to create dashboard: ${dashboardResult.error.message}`)
    }

    const dashboardWithUrl = {
        ...dashboardResult.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/dashboard/${dashboardResult.data.id}`,
    }

    return { content: [{ type: 'text', text: JSON.stringify(dashboardWithUrl) }] }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'dashboard-create',
    schema,
    handler: createHandler,
})

export default tool
