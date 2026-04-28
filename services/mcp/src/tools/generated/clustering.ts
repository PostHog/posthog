// AUTO-GENERATED from products/llm_analytics/mcp/clustering.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    LlmAnalyticsClusteringJobsListQueryParams,
    LlmAnalyticsClusteringJobsRetrieveParams,
} from '@/generated/clustering/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ClusteringJobGetSchema = LlmAnalyticsClusteringJobsRetrieveParams.omit({ project_id: true })

const clusteringJobGet = (): ToolBase<typeof ClusteringJobGetSchema, Schemas.ClusteringJob> => ({
    name: 'clustering-job-get',
    schema: ClusteringJobGetSchema,
    handler: async (context: Context, params: z.infer<typeof ClusteringJobGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ClusteringJob>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/clustering_jobs/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const ClusteringJobsListSchema = LlmAnalyticsClusteringJobsListQueryParams

const clusteringJobsList = (): ToolBase<typeof ClusteringJobsListSchema, Schemas.PaginatedClusteringJobList> => ({
    name: 'clustering-jobs-list',
    schema: ClusteringJobsListSchema,
    handler: async (context: Context, params: z.infer<typeof ClusteringJobsListSchema>) => {
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

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'clustering-job-get': clusteringJobGet,
    'clustering-jobs-list': clusteringJobsList,
}
