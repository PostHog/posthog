// AUTO-GENERATED from products/exports/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { ChartImagesCreateBody } from '@/generated/exports/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ChartImagePublishSchema = ChartImagesCreateBody.extend({
    image_base64: ChartImagesCreateBody.shape['image_base64'].describe(
        'Base64-encoded PNG bytes of the image you rendered.'
    ),
})

const chartImagePublish = (): ToolBase<typeof ChartImagePublishSchema, Schemas.ChartImage> => ({
    name: 'chart-image-publish',
    schema: ChartImagePublishSchema,
    handler: async (context: Context, params: z.infer<typeof ChartImagePublishSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.image_base64 !== undefined) {
            body['image_base64'] = params.image_base64
        }
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.insight_short_id !== undefined) {
            body['insight_short_id'] = params.insight_short_id
        }
        const result = await context.api.request<Schemas.ChartImage>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/chart_images/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'chart-image-publish': chartImagePublish,
}
