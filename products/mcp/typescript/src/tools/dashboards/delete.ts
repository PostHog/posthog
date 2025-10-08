import { DashboardDeleteSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = DashboardDeleteSchema

type Params = z.infer<typeof schema>

export const deleteHandler = async (context: Context, params: Params) => {
    const { dashboardId } = params
    const projectId = await context.stateManager.getProjectId()
    const result = await context.api.dashboards({ projectId }).delete({ dashboardId })

    if (!result.success) {
        throw new Error(`Failed to delete dashboard: ${result.error.message}`)
    }

    return { content: [{ type: 'text', text: JSON.stringify(result.data) }] }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'dashboard-delete',
    schema,
    handler: deleteHandler,
})

export default tool
