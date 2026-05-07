// AUTO-GENERATED from products/web_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { WebAnalyticsWeeklyDigestQueryParams } from '@/generated/web_analytics/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const WebAnalyticsWeeklyDigestSchema = WebAnalyticsWeeklyDigestQueryParams

const webAnalyticsWeeklyDigest = (): ToolBase<typeof WebAnalyticsWeeklyDigestSchema, Schemas.WeeklyDigestResponse> => ({
    name: 'web-analytics-weekly-digest',
    schema: WebAnalyticsWeeklyDigestSchema,
    handler: async (context: Context, params: z.infer<typeof WebAnalyticsWeeklyDigestSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.WeeklyDigestResponse>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/web_analytics/weekly_digest/`,
            query: {
                compare: params.compare,
                days: params.days,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'web-analytics-weekly-digest': webAnalyticsWeeklyDigest,
}
