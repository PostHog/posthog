// AUTO-GENERATED from products/llm_analytics/mcp/summarization.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { LlmAnalyticsSentimentCreateBody, LlmAnalyticsSummarizationCreateBody } from '@/generated/summarization/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const SentimentAnalyzeSchema = LlmAnalyticsSentimentCreateBody

const sentimentAnalyze = (): ToolBase<typeof SentimentAnalyzeSchema, Schemas.SentimentBatchResponse> => ({
    name: 'sentiment-analyze',
    schema: SentimentAnalyzeSchema,
    handler: async (context: Context, params: z.infer<typeof SentimentAnalyzeSchema>) => {
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/sentiment/`,
            body,
        })
        return result
    },
})

const TraceSummarizeSchema = LlmAnalyticsSummarizationCreateBody

const traceSummarize = (): ToolBase<typeof TraceSummarizeSchema, Schemas.SummarizeResponse> => ({
    name: 'trace-summarize',
    schema: TraceSummarizeSchema,
    handler: async (context: Context, params: z.infer<typeof TraceSummarizeSchema>) => {
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/summarization/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'sentiment-analyze': sentimentAnalyze,
    'trace-summarize': traceSummarize,
}
