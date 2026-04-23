// AUTO-GENERATED from products/llm_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    LlmAnalyticsClusteringJobsListQueryParams,
    LlmAnalyticsClusteringJobsRetrieveParams,
    LlmAnalyticsEvaluationSummaryCreateBody,
    LlmAnalyticsSentimentCreateBody,
    LlmAnalyticsSummarizationCreateBody,
} from '@/generated/llm_analytics/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const LlmAnalyticsClusteringJobsListSchema = LlmAnalyticsClusteringJobsListQueryParams

const llmAnalyticsClusteringJobsList = (): ToolBase<
    typeof LlmAnalyticsClusteringJobsListSchema,
    Schemas.PaginatedClusteringJobList
> => ({
    name: 'llm-analytics-clustering-jobs-list',
    schema: LlmAnalyticsClusteringJobsListSchema,
    handler: async (context: Context, params: z.infer<typeof LlmAnalyticsClusteringJobsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedClusteringJobList>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/clustering_jobs/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const LlmAnalyticsEvaluationSummaryCreateSchema = LlmAnalyticsEvaluationSummaryCreateBody

const llmAnalyticsEvaluationSummaryCreate = (): ToolBase<
    typeof LlmAnalyticsEvaluationSummaryCreateSchema,
    Schemas.EvaluationSummaryResponse
> => ({
    name: 'llm-analytics-evaluation-summary-create',
    schema: LlmAnalyticsEvaluationSummaryCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmAnalyticsEvaluationSummaryCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.evaluation_id !== undefined) {
            body['evaluation_id'] = params.evaluation_id
        }
        if (params.filter !== undefined) {
            body['filter'] = params.filter
        }
        if (params.generation_ids !== undefined) {
            body['generation_ids'] = params.generation_ids
        }
        if (params.force_refresh !== undefined) {
            body['force_refresh'] = params.force_refresh
        }
        const result = await context.api.request<Schemas.EvaluationSummaryResponse>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_summary/`,
            body,
        })
        return result
    },
})

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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/sentiment/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/summarization/`,
            body,
        })
        return result
    },
})

const LlmAnalyticsClusteringJobsRetrieveSchema = LlmAnalyticsClusteringJobsRetrieveParams.omit({ project_id: true })

const llmAnalyticsClusteringJobsRetrieve = (): ToolBase<
    typeof LlmAnalyticsClusteringJobsRetrieveSchema,
    Schemas.ClusteringJob
> => ({
    name: 'llm-analytics-clustering-jobs-retrieve',
    schema: LlmAnalyticsClusteringJobsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof LlmAnalyticsClusteringJobsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ClusteringJob>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/clustering_jobs/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'llm-analytics-clustering-jobs-list': llmAnalyticsClusteringJobsList,
    'llm-analytics-evaluation-summary-create': llmAnalyticsEvaluationSummaryCreate,
    'llm-analytics-sentiment-create': llmAnalyticsSentimentCreate,
    'llm-analytics-summarization-create': llmAnalyticsSummarizationCreate,
    'llm-analytics-clustering-jobs-retrieve': llmAnalyticsClusteringJobsRetrieve,
}
