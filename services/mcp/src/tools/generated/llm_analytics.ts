// AUTO-GENERATED from products/llm_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    LlmAnalyticsClusteringJobsListQueryParams,
    LlmAnalyticsClusteringJobsRetrieveParams,
    LlmAnalyticsEvaluationSummaryCreateBody,
    LlmAnalyticsReviewQueueItemsCreateBody,
    LlmAnalyticsReviewQueueItemsDestroyParams,
    LlmAnalyticsReviewQueueItemsListQueryParams,
    LlmAnalyticsReviewQueueItemsPartialUpdateBody,
    LlmAnalyticsReviewQueueItemsPartialUpdateParams,
    LlmAnalyticsReviewQueueItemsRetrieveParams,
    LlmAnalyticsReviewQueuesCreateBody,
    LlmAnalyticsReviewQueuesDestroyParams,
    LlmAnalyticsReviewQueuesListQueryParams,
    LlmAnalyticsReviewQueuesPartialUpdateBody,
    LlmAnalyticsReviewQueuesPartialUpdateParams,
    LlmAnalyticsReviewQueuesRetrieveParams,
    LlmAnalyticsSentimentCreateBody,
    LlmAnalyticsSummarizationCreateBody,
    LlmAnalyticsTraceReviewsCreateBody,
    LlmAnalyticsTraceReviewsDestroyParams,
    LlmAnalyticsTraceReviewsListQueryParams,
    LlmAnalyticsTraceReviewsPartialUpdateBody,
    LlmAnalyticsTraceReviewsPartialUpdateParams,
    LlmAnalyticsTraceReviewsRetrieveParams,
} from '@/generated/llm_analytics/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
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

const LlmAnalyticsReviewQueueItemsCreateSchema = LlmAnalyticsReviewQueueItemsCreateBody

const llmAnalyticsReviewQueueItemsCreate = (): ToolBase<
    typeof LlmAnalyticsReviewQueueItemsCreateSchema,
    WithPostHogUrl<Schemas.ReviewQueueItem>
> => ({
    name: 'llm-analytics-review-queue-items-create',
    schema: LlmAnalyticsReviewQueueItemsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmAnalyticsReviewQueueItemsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.queue_id !== undefined) {
            body['queue_id'] = params.queue_id
        }
        if (params.trace_id !== undefined) {
            body['trace_id'] = params.trace_id
        }
        const result = await context.api.request<Schemas.ReviewQueueItem>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/review_queue_items/`,
            body,
        })
        return await withPostHogUrl(context, result, `/llm-analytics/traces/${result.trace_id}`)
    },
})

const LlmAnalyticsReviewQueueItemsDestroySchema = LlmAnalyticsReviewQueueItemsDestroyParams.omit({ project_id: true })

const llmAnalyticsReviewQueueItemsDestroy = (): ToolBase<
    typeof LlmAnalyticsReviewQueueItemsDestroySchema,
    unknown
> => ({
    name: 'llm-analytics-review-queue-items-destroy',
    schema: LlmAnalyticsReviewQueueItemsDestroySchema,
    handler: async (context: Context, params: z.infer<typeof LlmAnalyticsReviewQueueItemsDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/review_queue_items/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const LlmAnalyticsReviewQueueItemsListSchema = LlmAnalyticsReviewQueueItemsListQueryParams

const llmAnalyticsReviewQueueItemsList = (): ToolBase<
    typeof LlmAnalyticsReviewQueueItemsListSchema,
    WithPostHogUrl<Schemas.PaginatedReviewQueueItemList>
> => ({
    name: 'llm-analytics-review-queue-items-list',
    schema: LlmAnalyticsReviewQueueItemsListSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof LlmAnalyticsReviewQueueItemsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedReviewQueueItemList>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/review_queue_items/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                order_by: params.order_by,
                queue_id: params.queue_id,
                search: params.search,
                trace_id: params.trace_id,
                trace_id__in: params.trace_id__in,
            },
        })
        return await withPostHogUrl(
            context,
            {
                ...result,
                results: await Promise.all(
                    (result.results ?? []).map((item) =>
                        withPostHogUrl(context, item, `/llm-analytics/traces/${item.trace_id}`)
                    )
                ),
            },
            '/llm-analytics'
        )
    },
})

const LlmAnalyticsReviewQueueItemsPartialUpdateSchema = LlmAnalyticsReviewQueueItemsPartialUpdateParams.omit({
    project_id: true,
}).extend(LlmAnalyticsReviewQueueItemsPartialUpdateBody.shape)

const llmAnalyticsReviewQueueItemsPartialUpdate = (): ToolBase<
    typeof LlmAnalyticsReviewQueueItemsPartialUpdateSchema,
    WithPostHogUrl<Schemas.ReviewQueueItem>
> => ({
    name: 'llm-analytics-review-queue-items-partial-update',
    schema: LlmAnalyticsReviewQueueItemsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmAnalyticsReviewQueueItemsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.queue_id !== undefined) {
            body['queue_id'] = params.queue_id
        }
        const result = await context.api.request<Schemas.ReviewQueueItem>({
            method: 'PATCH',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/review_queue_items/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/llm-analytics/traces/${result.trace_id}`)
    },
})

const LlmAnalyticsReviewQueueItemsRetrieveSchema = LlmAnalyticsReviewQueueItemsRetrieveParams.omit({ project_id: true })

const llmAnalyticsReviewQueueItemsRetrieve = (): ToolBase<
    typeof LlmAnalyticsReviewQueueItemsRetrieveSchema,
    WithPostHogUrl<Schemas.ReviewQueueItem>
> => ({
    name: 'llm-analytics-review-queue-items-retrieve',
    schema: LlmAnalyticsReviewQueueItemsRetrieveSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof LlmAnalyticsReviewQueueItemsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReviewQueueItem>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/review_queue_items/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/llm-analytics/traces/${result.trace_id}`)
    },
})

const LlmAnalyticsReviewQueuesCreateSchema = LlmAnalyticsReviewQueuesCreateBody

const llmAnalyticsReviewQueuesCreate = (): ToolBase<
    typeof LlmAnalyticsReviewQueuesCreateSchema,
    WithPostHogUrl<Schemas.ReviewQueue>
> => ({
    name: 'llm-analytics-review-queues-create',
    schema: LlmAnalyticsReviewQueuesCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmAnalyticsReviewQueuesCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        const result = await context.api.request<Schemas.ReviewQueue>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/review_queues/`,
            body,
        })
        return await withPostHogUrl(context, result, `/llm-analytics/reviews?queue_id=${result.id}`)
    },
})

const LlmAnalyticsReviewQueuesDestroySchema = LlmAnalyticsReviewQueuesDestroyParams.omit({ project_id: true })

const llmAnalyticsReviewQueuesDestroy = (): ToolBase<typeof LlmAnalyticsReviewQueuesDestroySchema, unknown> => ({
    name: 'llm-analytics-review-queues-destroy',
    schema: LlmAnalyticsReviewQueuesDestroySchema,
    handler: async (context: Context, params: z.infer<typeof LlmAnalyticsReviewQueuesDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/review_queues/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const LlmAnalyticsReviewQueuesListSchema = LlmAnalyticsReviewQueuesListQueryParams

const llmAnalyticsReviewQueuesList = (): ToolBase<
    typeof LlmAnalyticsReviewQueuesListSchema,
    WithPostHogUrl<Schemas.PaginatedReviewQueueList>
> => ({
    name: 'llm-analytics-review-queues-list',
    schema: LlmAnalyticsReviewQueuesListSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof LlmAnalyticsReviewQueuesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedReviewQueueList>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/review_queues/`,
            query: {
                limit: params.limit,
                name: params.name,
                offset: params.offset,
                order_by: params.order_by,
                search: params.search,
            },
        })
        return await withPostHogUrl(
            context,
            {
                ...result,
                results: await Promise.all(
                    (result.results ?? []).map((item) =>
                        withPostHogUrl(context, item, `/llm-analytics/reviews?queue_id=${item.id}`)
                    )
                ),
            },
            '/llm-analytics'
        )
    },
})

const LlmAnalyticsReviewQueuesPartialUpdateSchema = LlmAnalyticsReviewQueuesPartialUpdateParams.omit({
    project_id: true,
}).extend(LlmAnalyticsReviewQueuesPartialUpdateBody.shape)

const llmAnalyticsReviewQueuesPartialUpdate = (): ToolBase<
    typeof LlmAnalyticsReviewQueuesPartialUpdateSchema,
    WithPostHogUrl<Schemas.ReviewQueue>
> => ({
    name: 'llm-analytics-review-queues-partial-update',
    schema: LlmAnalyticsReviewQueuesPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmAnalyticsReviewQueuesPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        const result = await context.api.request<Schemas.ReviewQueue>({
            method: 'PATCH',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/review_queues/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/llm-analytics/reviews?queue_id=${result.id}`)
    },
})

const LlmAnalyticsReviewQueuesRetrieveSchema = LlmAnalyticsReviewQueuesRetrieveParams.omit({ project_id: true })

const llmAnalyticsReviewQueuesRetrieve = (): ToolBase<
    typeof LlmAnalyticsReviewQueuesRetrieveSchema,
    WithPostHogUrl<Schemas.ReviewQueue>
> => ({
    name: 'llm-analytics-review-queues-retrieve',
    schema: LlmAnalyticsReviewQueuesRetrieveSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof LlmAnalyticsReviewQueuesRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReviewQueue>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/review_queues/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/llm-analytics/reviews?queue_id=${result.id}`)
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

const LlmAnalyticsTraceReviewsCreateSchema = LlmAnalyticsTraceReviewsCreateBody

const llmAnalyticsTraceReviewsCreate = (): ToolBase<
    typeof LlmAnalyticsTraceReviewsCreateSchema,
    WithPostHogUrl<Schemas.TraceReview>
> => ({
    name: 'llm-analytics-trace-reviews-create',
    schema: LlmAnalyticsTraceReviewsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmAnalyticsTraceReviewsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.trace_id !== undefined) {
            body['trace_id'] = params.trace_id
        }
        if (params.comment !== undefined) {
            body['comment'] = params.comment
        }
        if (params.scores !== undefined) {
            body['scores'] = params.scores
        }
        if (params.queue_id !== undefined) {
            body['queue_id'] = params.queue_id
        }
        const result = await context.api.request<Schemas.TraceReview>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/trace_reviews/`,
            body,
        })
        return await withPostHogUrl(context, result, `/llm-analytics/traces/${result.trace_id}`)
    },
})

const LlmAnalyticsTraceReviewsDestroySchema = LlmAnalyticsTraceReviewsDestroyParams.omit({ project_id: true })

const llmAnalyticsTraceReviewsDestroy = (): ToolBase<typeof LlmAnalyticsTraceReviewsDestroySchema, unknown> => ({
    name: 'llm-analytics-trace-reviews-destroy',
    schema: LlmAnalyticsTraceReviewsDestroySchema,
    handler: async (context: Context, params: z.infer<typeof LlmAnalyticsTraceReviewsDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/trace_reviews/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const LlmAnalyticsTraceReviewsListSchema = LlmAnalyticsTraceReviewsListQueryParams

const llmAnalyticsTraceReviewsList = (): ToolBase<
    typeof LlmAnalyticsTraceReviewsListSchema,
    WithPostHogUrl<Schemas.PaginatedTraceReviewList>
> => ({
    name: 'llm-analytics-trace-reviews-list',
    schema: LlmAnalyticsTraceReviewsListSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof LlmAnalyticsTraceReviewsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedTraceReviewList>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/trace_reviews/`,
            query: {
                definition_id: params.definition_id,
                definition_id__in: params.definition_id__in,
                limit: params.limit,
                offset: params.offset,
                order_by: params.order_by,
                search: params.search,
                trace_id: params.trace_id,
                trace_id__in: params.trace_id__in,
            },
        })
        return await withPostHogUrl(
            context,
            {
                ...result,
                results: await Promise.all(
                    (result.results ?? []).map((item) =>
                        withPostHogUrl(context, item, `/llm-analytics/traces/${item.trace_id}`)
                    )
                ),
            },
            '/llm-analytics'
        )
    },
})

const LlmAnalyticsTraceReviewsPartialUpdateSchema = LlmAnalyticsTraceReviewsPartialUpdateParams.omit({
    project_id: true,
}).extend(LlmAnalyticsTraceReviewsPartialUpdateBody.shape)

const llmAnalyticsTraceReviewsPartialUpdate = (): ToolBase<
    typeof LlmAnalyticsTraceReviewsPartialUpdateSchema,
    WithPostHogUrl<Schemas.TraceReview>
> => ({
    name: 'llm-analytics-trace-reviews-partial-update',
    schema: LlmAnalyticsTraceReviewsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmAnalyticsTraceReviewsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.trace_id !== undefined) {
            body['trace_id'] = params.trace_id
        }
        if (params.comment !== undefined) {
            body['comment'] = params.comment
        }
        if (params.scores !== undefined) {
            body['scores'] = params.scores
        }
        if (params.queue_id !== undefined) {
            body['queue_id'] = params.queue_id
        }
        const result = await context.api.request<Schemas.TraceReview>({
            method: 'PATCH',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/trace_reviews/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/llm-analytics/traces/${result.trace_id}`)
    },
})

const LlmAnalyticsTraceReviewsRetrieveSchema = LlmAnalyticsTraceReviewsRetrieveParams.omit({ project_id: true })

const llmAnalyticsTraceReviewsRetrieve = (): ToolBase<
    typeof LlmAnalyticsTraceReviewsRetrieveSchema,
    WithPostHogUrl<Schemas.TraceReview>
> => ({
    name: 'llm-analytics-trace-reviews-retrieve',
    schema: LlmAnalyticsTraceReviewsRetrieveSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof LlmAnalyticsTraceReviewsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TraceReview>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/trace_reviews/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/llm-analytics/traces/${result.trace_id}`)
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'llm-analytics-clustering-jobs-list': llmAnalyticsClusteringJobsList,
    'llm-analytics-clustering-jobs-retrieve': llmAnalyticsClusteringJobsRetrieve,
    'llm-analytics-evaluation-summary-create': llmAnalyticsEvaluationSummaryCreate,
    'llm-analytics-review-queue-items-create': llmAnalyticsReviewQueueItemsCreate,
    'llm-analytics-review-queue-items-destroy': llmAnalyticsReviewQueueItemsDestroy,
    'llm-analytics-review-queue-items-list': llmAnalyticsReviewQueueItemsList,
    'llm-analytics-review-queue-items-partial-update': llmAnalyticsReviewQueueItemsPartialUpdate,
    'llm-analytics-review-queue-items-retrieve': llmAnalyticsReviewQueueItemsRetrieve,
    'llm-analytics-review-queues-create': llmAnalyticsReviewQueuesCreate,
    'llm-analytics-review-queues-destroy': llmAnalyticsReviewQueuesDestroy,
    'llm-analytics-review-queues-list': llmAnalyticsReviewQueuesList,
    'llm-analytics-review-queues-partial-update': llmAnalyticsReviewQueuesPartialUpdate,
    'llm-analytics-review-queues-retrieve': llmAnalyticsReviewQueuesRetrieve,
    'llm-analytics-sentiment-create': llmAnalyticsSentimentCreate,
    'llm-analytics-summarization-create': llmAnalyticsSummarizationCreate,
    'llm-analytics-trace-reviews-create': llmAnalyticsTraceReviewsCreate,
    'llm-analytics-trace-reviews-destroy': llmAnalyticsTraceReviewsDestroy,
    'llm-analytics-trace-reviews-list': llmAnalyticsTraceReviewsList,
    'llm-analytics-trace-reviews-partial-update': llmAnalyticsTraceReviewsPartialUpdate,
    'llm-analytics-trace-reviews-retrieve': llmAnalyticsTraceReviewsRetrieve,
}
