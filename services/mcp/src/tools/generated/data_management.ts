// AUTO-GENERATED from services/mcp/definitions/data_management.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { IngestionWarningsV2ListQueryParams } from '@/generated/data_management/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const IngestionWarningsListSchema = IngestionWarningsV2ListQueryParams

const ingestionWarningsList = (): ToolBase<
    typeof IngestionWarningsListSchema,
    WithPostHogUrl<Schemas.IngestionWarningsV2Summary[]>
> => ({
    name: 'ingestion-warnings-list',
    schema: IngestionWarningsListSchema,
    handler: async (context: Context, params: z.infer<typeof IngestionWarningsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.IngestionWarningsV2Summary[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/ingestion_warnings_v2/`,
            query: {
                category: params.category,
                limit: params.limit,
                order_by: params.order_by,
                q: params.q,
                samples: params.samples,
                severity: params.severity,
                since: params.since,
                type: params.type,
                until: params.until,
            },
        })
        return await withPostHogUrl(context, result, '/data-management/ingestion-warnings-v2')
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'ingestion-warnings-list': ingestionWarningsList,
}
