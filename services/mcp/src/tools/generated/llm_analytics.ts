// AUTO-GENERATED from products/llm_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    LlmAnalyticsClusteringJobsListQueryParams,
    LlmAnalyticsClusteringJobsRetrieveParams,
    LlmAnalyticsSentimentCreateBody,
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
            path: `/api/environments/${projectId}/llm_analytics/clustering_jobs/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
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
            path: `/api/environments/${projectId}/llm_analytics/sentiment/`,
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
            path: `/api/environments/${projectId}/llm_analytics/clustering_jobs/${params.id}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'llm-analytics-clustering-jobs-list': llmAnalyticsClusteringJobsList,
    'llm-analytics-sentiment-create': llmAnalyticsSentimentCreate,
    'llm-analytics-clustering-jobs-retrieve': llmAnalyticsClusteringJobsRetrieve,
}
