// AUTO-GENERATED from services/mcp/definitions/sdk_health.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { SdkHealthReportRetrieveQueryParams } from '@/generated/sdk_health/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const SdkHealthGetSchema = SdkHealthReportRetrieveQueryParams.extend({
    force_refresh: SdkHealthReportRetrieveQueryParams.shape['force_refresh'].describe(
        'Set to true to bypass the Redis cache and re-query ClickHouse for SDK usage. Use sparingly — data is refreshed every 12 hours by a background job, so the cached answer is usually fine.'
    ),
})

const sdkHealthGet = (): ToolBase<typeof SdkHealthGetSchema, Schemas.SdkHealthReport> => ({
    name: 'sdk-health-get',
    schema: SdkHealthGetSchema,
    handler: async (context: Context, params: z.infer<typeof SdkHealthGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SdkHealthReport>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/sdk_health/report/`,
            query: {
                force_refresh: params.force_refresh,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'sdk-health-get': sdkHealthGet,
}
