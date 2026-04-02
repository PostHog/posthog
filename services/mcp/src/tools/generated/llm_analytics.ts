// AUTO-GENERATED from products/llm_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { LlmAnalyticsSentimentCreateBody } from '@/generated/llm_analytics/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const LlmAnalyticsSentimentCreateSchema = LlmAnalyticsSentimentCreateBody

const llmAnalyticsSentimentCreate = (): ToolBase<
    typeof LlmAnalyticsSentimentCreateSchema,
    Schemas.SentimentBatchResponse
> => ({
    name: 'llm-analytics-sentiment-create',
    schema: LlmAnalyticsSentimentCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmAnalyticsSentimentCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.ids !== undefined) {
            body['ids'] = params.ids
        }
        if (params.analysis_level !== undefined) {
            body['analysis_level'] = params.analysis_level
        }
        if (params.force_refresh !== undefined) {
            body['force_refresh'] = params.force_refresh
        }
        if (params.date_from !== undefined) {
            body['date_from'] = params.date_from
        }
        if (params.date_to !== undefined) {
            body['date_to'] = params.date_to
        }
        const result = await context.api.request<Schemas.SentimentBatchResponse>({
            method: 'POST',
            path: `/api/environments/${projectId}/llm_analytics/sentiment/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'llm-analytics-sentiment-create': llmAnalyticsSentimentCreate,
}
