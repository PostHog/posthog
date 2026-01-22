import type { z } from 'zod'

import { DashboardReorderTilesSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = DashboardReorderTilesSchema

type Params = z.infer<typeof schema>

export const reorderTilesHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { dashboardId, tileOrder } = params
    const projectId = await context.stateManager.getProjectId()

    const dashboardTilesResult = await context.api
        .dashboards({ projectId })
        .reorderTiles({ dashboardId, tileOrder })

    if (!dashboardTilesResult.success) {
        throw new Error(`Failed to reorder tiles: ${dashboardTilesResult.error.message}`)
    }

    return {
        ...dashboardTilesResult.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/dashboard/${dashboardId}`,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'dashboard-reorder-tiles',
    schema,
    handler: reorderTilesHandler,
})

export default tool
