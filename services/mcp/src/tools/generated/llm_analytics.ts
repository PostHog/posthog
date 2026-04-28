// AUTO-GENERATED from products/llm_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    LlmAnalyticsClusteringJobsListQueryParams,
    LlmAnalyticsClusteringJobsRetrieveParams,
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
    'llm-analytics-clustering-jobs-retrieve': llmAnalyticsClusteringJobsRetrieve,
}
