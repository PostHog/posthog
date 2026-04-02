// AUTO-GENERATED from products/llm_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { LlmAnalyticsSentimentCreateBody, LlmAnalyticsSummarizationCreateBody } from '@/generated/llm_analytics/api'
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
        if (params.trace_id !== undefined) {
            body['trace_id'] = params.trace_id
        }
        if (params.generation_id !== undefined) {
            body['generation_id'] = params.generation_id
        }
        if (params.date_from !== undefined) {
            body['date_from'] = params.date_from
        }
        if (params.date_to !== undefined) {
            body['date_to'] = params.date_to
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
    'llm-analytics-sentiment-create': llmAnalyticsSentimentCreate,
    'llm-analytics-summarization-create': llmAnalyticsSummarizationCreate,
}
