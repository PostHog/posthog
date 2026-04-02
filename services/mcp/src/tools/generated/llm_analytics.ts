// AUTO-GENERATED from products/llm_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { LlmAnalyticsSummarizationCreateBody } from '@/generated/llm_analytics/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const LlmAnalyticsSummarizationCreateSchema = LlmAnalyticsSummarizationCreateBody

const llmAnalyticsSummarizationCreate = (): ToolBase<
    typeof LlmAnalyticsSummarizationCreateSchema,
    Schemas.SummarizeResponse
> => ({
    name: 'llm-analytics-summarization-create',
    schema: LlmAnalyticsSummarizationCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmAnalyticsSummarizationCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.summarize_type !== undefined) {
            body['summarize_type'] = params.summarize_type
        }
        if (params.mode !== undefined) {
            body['mode'] = params.mode
        }
        if (params.data !== undefined) {
            body['data'] = params.data
        }
        if (params.force_refresh !== undefined) {
            body['force_refresh'] = params.force_refresh
        }
        if (params.model !== undefined) {
            body['model'] = params.model
        }
        const result = await context.api.request<Schemas.SummarizeResponse>({
            method: 'POST',
            path: `/api/environments/${projectId}/llm_analytics/summarization/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'llm-analytics-summarization-create': llmAnalyticsSummarizationCreate,
}
