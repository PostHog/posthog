import type { z } from 'zod'

import { DashboardAddTextCardSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = DashboardAddTextCardSchema

type Params = z.infer<typeof schema>

type Result = { dashboard_url: string; tile_id: number; body: string; color: string | null }

export const addTextCardHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const { data } = params
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.dashboards({ projectId }).addTextCard({
        data: {
            dashboardId: data.dashboardId,
            body: data.body,
            color: data.color,
        },
    })

    if (!result.success) {
        throw new Error(`Failed to add text card to dashboard: ${result.error.message}`)
    }

    // Find the newly added text tile (should be the last one with a text field)
    const textTiles = result.data.tiles?.filter((tile: any) => tile?.text?.body === data.body) ?? []
    const newTile = textTiles[textTiles.length - 1]

    return {
        dashboard_url: `${context.api.getProjectBaseUrl(projectId)}/dashboard/${data.dashboardId}`,
        tile_id: newTile?.id ?? 0,
        body: data.body,
        color: data.color ?? null,
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'add-text-card-to-dashboard',
    schema,
    handler: addTextCardHandler,
})

export default tool
