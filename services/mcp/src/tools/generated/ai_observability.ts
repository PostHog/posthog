// AUTO-GENERATED from products/ai_observability/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    EvaluationRunsCreateBody,
    EvaluationsCreateBody,
    EvaluationsDestroyParams,
    EvaluationsListQueryParams,
    EvaluationsPartialUpdateBody,
    EvaluationsPartialUpdateParams,
    EvaluationsRetrieveParams,
    EvaluationsTestHogCreateBody,
    LlmAnalyticsClusteringConfigSetEventFiltersCreateBody,
    LlmAnalyticsClusteringJobsCreateBody,
    LlmAnalyticsClusteringJobsDestroyParams,
    LlmAnalyticsClusteringJobsListQueryParams,
    LlmAnalyticsClusteringJobsPartialUpdateBody,
    LlmAnalyticsClusteringJobsPartialUpdateParams,
    LlmAnalyticsClusteringJobsRetrieveParams,
    LlmAnalyticsEvaluationConfigSetActiveKeyCreateBody,
    LlmAnalyticsEvaluationReportsCreateBody,
    LlmAnalyticsEvaluationReportsGenerateCreateParams,
    LlmAnalyticsEvaluationReportsListQueryParams,
    LlmAnalyticsEvaluationReportsPartialUpdateBody,
    LlmAnalyticsEvaluationReportsPartialUpdateParams,
    LlmAnalyticsEvaluationReportsRetrieveParams,
    LlmAnalyticsEvaluationReportsRunsListParams,
    LlmAnalyticsEvaluationReportsRunsListQueryParams,
    LlmAnalyticsEvaluationSummaryCreateBody,
    LlmAnalyticsModelsRetrieveQueryParams,
    LlmAnalyticsPersonalSpendListQueryParams,
    LlmAnalyticsProviderKeysListQueryParams,
    LlmAnalyticsProviderKeysRetrieveParams,
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
    LlmAnalyticsScoreDefinitionsCreateBody,
    LlmAnalyticsScoreDefinitionsListQueryParams,
    LlmAnalyticsScoreDefinitionsNewVersionCreateBody,
    LlmAnalyticsScoreDefinitionsNewVersionCreateParams,
    LlmAnalyticsScoreDefinitionsPartialUpdateBody,
    LlmAnalyticsScoreDefinitionsPartialUpdateParams,
    LlmAnalyticsScoreDefinitionsRetrieveParams,
    LlmAnalyticsSummarizationCreateBody,
    LlmAnalyticsTraceReviewsCreateBody,
    LlmAnalyticsTraceReviewsDestroyParams,
    LlmAnalyticsTraceReviewsListQueryParams,
    LlmAnalyticsTraceReviewsPartialUpdateBody,
    LlmAnalyticsTraceReviewsPartialUpdateParams,
    LlmAnalyticsTraceReviewsRetrieveParams,
    LlmPromptsCreateBody,
    LlmPromptsNameDuplicateCreateBody,
    LlmPromptsNameDuplicateCreateParams,
    LlmPromptsNamePartialUpdateBody,
    LlmPromptsNamePartialUpdateParams,
    LlmPromptsNameRetrieveParams,
    LlmPromptsNameRetrieveQueryParams,
    TaggersCreateBody,
    TaggersListQueryParams,
    TaggersTestHogCreateBody,
} from '@/generated/ai_observability/api'
import { PromptListInputSchema, ScoreDefinitionConfigSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const LlmaClusteringConfigGetSchema = z.object({})

const llmaClusteringConfigGet = (): ToolBase<typeof LlmaClusteringConfigGetSchema, Schemas.ClusteringConfig> => ({
    name: 'llma-clustering-config-get',
    schema: LlmaClusteringConfigGetSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof LlmaClusteringConfigGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ClusteringConfig>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/clustering_config/`,
        })
        return result
    },
})

const LlmaClusteringConfigSetEventFiltersSchema = LlmAnalyticsClusteringConfigSetEventFiltersCreateBody

const llmaClusteringConfigSetEventFilters = (): ToolBase<
    typeof LlmaClusteringConfigSetEventFiltersSchema,
    Schemas.ClusteringConfig
> => ({
    name: 'llma-clustering-config-set-event-filters',
    schema: LlmaClusteringConfigSetEventFiltersSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaClusteringConfigSetEventFiltersSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.event_filters !== undefined) {
            body['event_filters'] = params.event_filters
        }
        const result = await context.api.request<Schemas.ClusteringConfig>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/clustering_config/set_event_filters/`,
            body,
        })
        return result
    },
})

const LlmaClusteringJobCreateSchema = LlmAnalyticsClusteringJobsCreateBody

const llmaClusteringJobCreate = (): ToolBase<typeof LlmaClusteringJobCreateSchema, Schemas.ClusteringJob> => ({
    name: 'llma-clustering-job-create',
    schema: LlmaClusteringJobCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaClusteringJobCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.analysis_level !== undefined) {
            body['analysis_level'] = params.analysis_level
        }
        if (params.event_filters !== undefined) {
            body['event_filters'] = params.event_filters
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        const result = await context.api.request<Schemas.ClusteringJob>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/clustering_jobs/`,
            body,
        })
        return result
    },
})

const LlmaClusteringJobDeleteSchema = LlmAnalyticsClusteringJobsDestroyParams.omit({ project_id: true })

const llmaClusteringJobDelete = (): ToolBase<typeof LlmaClusteringJobDeleteSchema, unknown> => ({
    name: 'llma-clustering-job-delete',
    schema: LlmaClusteringJobDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaClusteringJobDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/clustering_jobs/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const LlmaClusteringJobGetSchema = LlmAnalyticsClusteringJobsRetrieveParams.omit({ project_id: true })

const llmaClusteringJobGet = (): ToolBase<typeof LlmaClusteringJobGetSchema, Schemas.ClusteringJob> => ({
    name: 'llma-clustering-job-get',
    schema: LlmaClusteringJobGetSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaClusteringJobGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ClusteringJob>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/clustering_jobs/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const LlmaClusteringJobListSchema = LlmAnalyticsClusteringJobsListQueryParams

const llmaClusteringJobList = (): ToolBase<typeof LlmaClusteringJobListSchema, Schemas.PaginatedClusteringJobList> => ({
    name: 'llma-clustering-job-list',
    schema: LlmaClusteringJobListSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaClusteringJobListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedClusteringJobList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/clustering_jobs/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const LlmaClusteringJobUpdateSchema = LlmAnalyticsClusteringJobsPartialUpdateParams.omit({ project_id: true }).extend(
    LlmAnalyticsClusteringJobsPartialUpdateBody.shape
)

const llmaClusteringJobUpdate = (): ToolBase<typeof LlmaClusteringJobUpdateSchema, Schemas.ClusteringJob> => ({
    name: 'llma-clustering-job-update',
    schema: LlmaClusteringJobUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaClusteringJobUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.analysis_level !== undefined) {
            body['analysis_level'] = params.analysis_level
        }
        if (params.event_filters !== undefined) {
            body['event_filters'] = params.event_filters
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        const result = await context.api.request<Schemas.ClusteringJob>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/clustering_jobs/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const LlmaEvaluationConfigGetSchema = z.object({})

const llmaEvaluationConfigGet = (): ToolBase<typeof LlmaEvaluationConfigGetSchema, Schemas.EvaluationConfig> => ({
    name: 'llma-evaluation-config-get',
    schema: LlmaEvaluationConfigGetSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof LlmaEvaluationConfigGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.EvaluationConfig>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_config/`,
        })
        return result
    },
})

const LlmaEvaluationConfigSetActiveKeySchema = LlmAnalyticsEvaluationConfigSetActiveKeyCreateBody

const llmaEvaluationConfigSetActiveKey = (): ToolBase<
    typeof LlmaEvaluationConfigSetActiveKeySchema,
    Schemas.EvaluationConfig
> => ({
    name: 'llma-evaluation-config-set-active-key',
    schema: LlmaEvaluationConfigSetActiveKeySchema,
    handler: async (context: Context, params: z.infer<typeof LlmaEvaluationConfigSetActiveKeySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.key_id !== undefined) {
            body['key_id'] = params.key_id
        }
        const result = await context.api.request<Schemas.EvaluationConfig>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_config/set_active_key/`,
            body,
        })
        return result
    },
})

const LlmaEvaluationCreateSchema = EvaluationsCreateBody

const llmaEvaluationCreate = (): ToolBase<typeof LlmaEvaluationCreateSchema, Schemas.Evaluation> => ({
    name: 'llma-evaluation-create',
    schema: LlmaEvaluationCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaEvaluationCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.evaluation_type !== undefined) {
            body['evaluation_type'] = params.evaluation_type
        }
        if (params.evaluation_config !== undefined) {
            body['evaluation_config'] = params.evaluation_config
        }
        if (params.output_type !== undefined) {
            body['output_type'] = params.output_type
        }
        if (params.output_config !== undefined) {
            body['output_config'] = params.output_config
        }
        if (params.conditions !== undefined) {
            body['conditions'] = params.conditions
        }
        if (params.target !== undefined) {
            body['target'] = params.target
        }
        if (params.target_config !== undefined) {
            body['target_config'] = params.target_config
        }
        if (params.model_configuration !== undefined) {
            body['model_configuration'] = params.model_configuration
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        const result = await context.api.request<Schemas.Evaluation>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/evaluations/`,
            body,
        })
        return result
    },
})

const LlmaEvaluationDeleteSchema = EvaluationsDestroyParams.omit({ project_id: true })

const llmaEvaluationDelete = (): ToolBase<typeof LlmaEvaluationDeleteSchema, Schemas.Evaluation> => ({
    name: 'llma-evaluation-delete',
    schema: LlmaEvaluationDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaEvaluationDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Evaluation>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/evaluations/${encodeURIComponent(String(params.id))}/`,
            body: { deleted: true },
        })
        return result
    },
})

const LlmaEvaluationGetSchema = EvaluationsRetrieveParams.omit({ project_id: true })

const llmaEvaluationGet = (): ToolBase<typeof LlmaEvaluationGetSchema, Schemas.Evaluation> => ({
    name: 'llma-evaluation-get',
    schema: LlmaEvaluationGetSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaEvaluationGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Evaluation>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/evaluations/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const LlmaEvaluationJudgeModelsSchema = LlmAnalyticsModelsRetrieveQueryParams

const llmaEvaluationJudgeModels = (): ToolBase<
    typeof LlmaEvaluationJudgeModelsSchema,
    Schemas.LLMModelsListResponse
> => ({
    name: 'llma-evaluation-judge-models',
    schema: LlmaEvaluationJudgeModelsSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaEvaluationJudgeModelsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LLMModelsListResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/models/`,
            query: {
                key_id: params.key_id,
                provider: params.provider,
            },
        })
        return result
    },
})

const LlmaEvaluationListSchema = EvaluationsListQueryParams

const llmaEvaluationList = (): ToolBase<typeof LlmaEvaluationListSchema, Schemas.PaginatedEvaluationList> => ({
    name: 'llma-evaluation-list',
    schema: LlmaEvaluationListSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaEvaluationListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedEvaluationList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/evaluations/`,
            query: {
                enabled: params.enabled,
                evaluation_type: params.evaluation_type,
                id__in: Array.isArray(params.id__in) ? params.id__in.join(',') || undefined : params.id__in,
                limit: params.limit,
                offset: params.offset,
                order_by: Array.isArray(params.order_by) ? params.order_by.join(',') || undefined : params.order_by,
                search: params.search,
            },
        })
        return result
    },
})

const LlmaEvaluationReportCreateSchema = LlmAnalyticsEvaluationReportsCreateBody

const llmaEvaluationReportCreate = (): ToolBase<typeof LlmaEvaluationReportCreateSchema, Schemas.EvaluationReport> => ({
    name: 'llma-evaluation-report-create',
    schema: LlmaEvaluationReportCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaEvaluationReportCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.evaluation !== undefined) {
            body['evaluation'] = params.evaluation
        }
        if (params.frequency !== undefined) {
            body['frequency'] = params.frequency
        }
        if (params.rrule !== undefined) {
            body['rrule'] = params.rrule
        }
        if (params.delivery_targets !== undefined) {
            body['delivery_targets'] = params.delivery_targets
        }
        if (params.max_sample_size !== undefined) {
            body['max_sample_size'] = params.max_sample_size
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.report_prompt_guidance !== undefined) {
            body['report_prompt_guidance'] = params.report_prompt_guidance
        }
        if (params.trigger_threshold !== undefined) {
            body['trigger_threshold'] = params.trigger_threshold
        }
        if (params.cooldown_minutes !== undefined) {
            body['cooldown_minutes'] = params.cooldown_minutes
        }
        if (params.daily_run_cap !== undefined) {
            body['daily_run_cap'] = params.daily_run_cap
        }
        const result = await context.api.request<Schemas.EvaluationReport>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_reports/`,
            body,
        })
        return result
    },
})

const LlmaEvaluationReportGenerateSchema = LlmAnalyticsEvaluationReportsGenerateCreateParams.omit({ project_id: true })

const llmaEvaluationReportGenerate = (): ToolBase<typeof LlmaEvaluationReportGenerateSchema, unknown> => ({
    name: 'llma-evaluation-report-generate',
    schema: LlmaEvaluationReportGenerateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaEvaluationReportGenerateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_reports/${encodeURIComponent(String(params.id))}/generate/`,
        })
        return result
    },
})

const LlmaEvaluationReportGetSchema = LlmAnalyticsEvaluationReportsRetrieveParams.omit({ project_id: true })

const llmaEvaluationReportGet = (): ToolBase<typeof LlmaEvaluationReportGetSchema, Schemas.EvaluationReport> => ({
    name: 'llma-evaluation-report-get',
    schema: LlmaEvaluationReportGetSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaEvaluationReportGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.EvaluationReport>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_reports/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const LlmaEvaluationReportListSchema = LlmAnalyticsEvaluationReportsListQueryParams

const llmaEvaluationReportList = (): ToolBase<
    typeof LlmaEvaluationReportListSchema,
    Schemas.PaginatedEvaluationReportList
> => ({
    name: 'llma-evaluation-report-list',
    schema: LlmaEvaluationReportListSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaEvaluationReportListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedEvaluationReportList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_reports/`,
            query: {
                evaluation: params.evaluation,
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const LlmaEvaluationReportRunListSchema = LlmAnalyticsEvaluationReportsRunsListParams.omit({ project_id: true }).extend(
    LlmAnalyticsEvaluationReportsRunsListQueryParams.shape
)

const llmaEvaluationReportRunList = (): ToolBase<
    typeof LlmaEvaluationReportRunListSchema,
    Schemas.PaginatedEvaluationReportRunList
> => ({
    name: 'llma-evaluation-report-run-list',
    schema: LlmaEvaluationReportRunListSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaEvaluationReportRunListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedEvaluationReportRunList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_reports/${encodeURIComponent(String(params.id))}/runs/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const LlmaEvaluationReportUpdateSchema = LlmAnalyticsEvaluationReportsPartialUpdateParams.omit({
    project_id: true,
}).extend(LlmAnalyticsEvaluationReportsPartialUpdateBody.shape)

const llmaEvaluationReportUpdate = (): ToolBase<
    typeof LlmaEvaluationReportUpdateSchema,
    Schemas.EvaluationReportUpdate
> => ({
    name: 'llma-evaluation-report-update',
    schema: LlmaEvaluationReportUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaEvaluationReportUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.frequency !== undefined) {
            body['frequency'] = params.frequency
        }
        if (params.rrule !== undefined) {
            body['rrule'] = params.rrule
        }
        if (params.delivery_targets !== undefined) {
            body['delivery_targets'] = params.delivery_targets
        }
        if (params.max_sample_size !== undefined) {
            body['max_sample_size'] = params.max_sample_size
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.report_prompt_guidance !== undefined) {
            body['report_prompt_guidance'] = params.report_prompt_guidance
        }
        if (params.trigger_threshold !== undefined) {
            body['trigger_threshold'] = params.trigger_threshold
        }
        if (params.cooldown_minutes !== undefined) {
            body['cooldown_minutes'] = params.cooldown_minutes
        }
        if (params.daily_run_cap !== undefined) {
            body['daily_run_cap'] = params.daily_run_cap
        }
        const result = await context.api.request<Schemas.EvaluationReportUpdate>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_reports/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const LlmaEvaluationRunSchema = EvaluationRunsCreateBody

const llmaEvaluationRun = (): ToolBase<typeof LlmaEvaluationRunSchema, unknown> => ({
    name: 'llma-evaluation-run',
    schema: LlmaEvaluationRunSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaEvaluationRunSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.evaluation_id !== undefined) {
            body['evaluation_id'] = params.evaluation_id
        }
        if (params.target_event_id !== undefined) {
            body['target_event_id'] = params.target_event_id
        }
        if (params.timestamp !== undefined) {
            body['timestamp'] = params.timestamp
        }
        if (params.event !== undefined) {
            body['event'] = params.event
        }
        if (params.distinct_id !== undefined) {
            body['distinct_id'] = params.distinct_id
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/evaluation_runs/`,
            body,
        })
        return result
    },
})

const LlmaEvaluationSummaryCreateSchema = LlmAnalyticsEvaluationSummaryCreateBody

const llmaEvaluationSummaryCreate = (): ToolBase<
    typeof LlmaEvaluationSummaryCreateSchema,
    Schemas.EvaluationSummaryResponse
> => ({
    name: 'llma-evaluation-summary-create',
    schema: LlmaEvaluationSummaryCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaEvaluationSummaryCreateSchema>) => {
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_summary/`,
            body,
        })
        return result
    },
})

const LlmaEvaluationTestHogSchema = EvaluationsTestHogCreateBody

const llmaEvaluationTestHog = (): ToolBase<typeof LlmaEvaluationTestHogSchema, Schemas.TestHogResponse> => ({
    name: 'llma-evaluation-test-hog',
    schema: LlmaEvaluationTestHogSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaEvaluationTestHogSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.source !== undefined) {
            body['source'] = params.source
        }
        if (params.sample_count !== undefined) {
            body['sample_count'] = params.sample_count
        }
        if (params.allows_na !== undefined) {
            body['allows_na'] = params.allows_na
        }
        if (params.conditions !== undefined) {
            body['conditions'] = params.conditions
        }
        const result = await context.api.request<Schemas.TestHogResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/evaluations/test_hog/`,
            body,
        })
        return result
    },
})

const LlmaEvaluationUpdateSchema = EvaluationsPartialUpdateParams.omit({ project_id: true }).extend(
    EvaluationsPartialUpdateBody.shape
)

const llmaEvaluationUpdate = (): ToolBase<typeof LlmaEvaluationUpdateSchema, Schemas.Evaluation> => ({
    name: 'llma-evaluation-update',
    schema: LlmaEvaluationUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaEvaluationUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.evaluation_type !== undefined) {
            body['evaluation_type'] = params.evaluation_type
        }
        if (params.evaluation_config !== undefined) {
            body['evaluation_config'] = params.evaluation_config
        }
        if (params.output_type !== undefined) {
            body['output_type'] = params.output_type
        }
        if (params.output_config !== undefined) {
            body['output_config'] = params.output_config
        }
        if (params.conditions !== undefined) {
            body['conditions'] = params.conditions
        }
        if (params.target !== undefined) {
            body['target'] = params.target
        }
        if (params.target_config !== undefined) {
            body['target_config'] = params.target_config
        }
        if (params.model_configuration !== undefined) {
            body['model_configuration'] = params.model_configuration
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        const result = await context.api.request<Schemas.Evaluation>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/evaluations/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const LlmaPersonalSpendSchema = LlmAnalyticsPersonalSpendListQueryParams

const llmaPersonalSpend = (): ToolBase<typeof LlmaPersonalSpendSchema, Schemas.PersonalSpendAnalysisResponse[]> => ({
    name: 'llma-personal-spend',
    schema: LlmaPersonalSpendSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaPersonalSpendSchema>) => {
        const result = await context.api.request<Schemas.PersonalSpendAnalysisResponse[]>({
            method: 'GET',
            path: `/api/llm_analytics/@me/spend/`,
            query: {
                date_from: params.date_from,
                date_to: params.date_to,
                limit: params.limit,
                product: params.product,
                refresh: params.refresh,
            },
        })
        return result
    },
})

const LlmaPromptCreateSchema = LlmPromptsCreateBody.omit({ config: true, tags: true })

const llmaPromptCreate = (): ToolBase<typeof LlmaPromptCreateSchema, Schemas.LLMPrompt> => ({
    name: 'llma-prompt-create',
    schema: LlmaPromptCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaPromptCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.prompt !== undefined) {
            body['prompt'] = params.prompt
        }
        if (params.version_description !== undefined) {
            body['version_description'] = params.version_description
        }
        const result = await context.api.request<Schemas.LLMPrompt>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_prompts/`,
            body,
        })
        return result
    },
})

const LlmaPromptDuplicateSchema = LlmPromptsNameDuplicateCreateParams.omit({ project_id: true }).extend(
    LlmPromptsNameDuplicateCreateBody.shape
)

const llmaPromptDuplicate = (): ToolBase<typeof LlmaPromptDuplicateSchema, Schemas.LLMPrompt> => ({
    name: 'llma-prompt-duplicate',
    schema: LlmaPromptDuplicateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaPromptDuplicateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.new_name !== undefined) {
            body['new_name'] = params.new_name
        }
        const result = await context.api.request<Schemas.LLMPrompt>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_prompts/name/${encodeURIComponent(String(params.prompt_name))}/duplicate/`,
            body,
        })
        return result
    },
})

const LlmaPromptGetSchema = LlmPromptsNameRetrieveParams.omit({ project_id: true }).extend(
    LlmPromptsNameRetrieveQueryParams.shape
)

const llmaPromptGet = (): ToolBase<typeof LlmaPromptGetSchema, Schemas.LLMPromptPublic> => ({
    name: 'llma-prompt-get',
    schema: LlmaPromptGetSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaPromptGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LLMPromptPublic>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_prompts/name/${encodeURIComponent(String(params.prompt_name))}/`,
            query: {
                content: params.content,
                version: params.version,
            },
        })
        return result
    },
})

const LlmaPromptListSchema = PromptListInputSchema

const llmaPromptList = (): ToolBase<
    typeof LlmaPromptListSchema,
    Omit<Schemas.PaginatedLLMPromptListList, 'results'> & {
        results: (Omit<Schemas.LLMPromptList, 'prompt'> & { prompt?: unknown })[]
    }
> => ({
    name: 'llma-prompt-list',
    schema: LlmaPromptListSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaPromptListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const parsedParams = LlmaPromptListSchema.parse(params)
        const result = await context.api.request<
            Omit<Schemas.PaginatedLLMPromptListList, 'results'> & {
                results: (Omit<Schemas.LLMPromptList, 'prompt'> & { prompt?: unknown })[]
            }
        >({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_prompts/`,
            query: parsedParams,
        })
        return result
    },
})

const LlmaPromptUpdateSchema = LlmPromptsNamePartialUpdateParams.omit({ project_id: true }).extend(
    LlmPromptsNamePartialUpdateBody.omit({ config: true }).shape
)

const llmaPromptUpdate = (): ToolBase<typeof LlmaPromptUpdateSchema, Schemas.LLMPrompt> => ({
    name: 'llma-prompt-update',
    schema: LlmaPromptUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaPromptUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.prompt !== undefined) {
            body['prompt'] = params.prompt
        }
        if (params.edits !== undefined) {
            body['edits'] = params.edits
        }
        if (params.base_version !== undefined) {
            body['base_version'] = params.base_version
        }
        if (params.version_description !== undefined) {
            body['version_description'] = params.version_description
        }
        const result = await context.api.request<Schemas.LLMPrompt>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_prompts/name/${encodeURIComponent(String(params.prompt_name))}/`,
            body,
        })
        return result
    },
})

const LlmaProviderKeyGetSchema = LlmAnalyticsProviderKeysRetrieveParams.omit({ project_id: true })

const llmaProviderKeyGet = (): ToolBase<typeof LlmaProviderKeyGetSchema, Schemas.LLMProviderKey> => ({
    name: 'llma-provider-key-get',
    schema: LlmaProviderKeyGetSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaProviderKeyGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LLMProviderKey>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/provider_keys/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const LlmaProviderKeyListSchema = LlmAnalyticsProviderKeysListQueryParams

const llmaProviderKeyList = (): ToolBase<
    typeof LlmaProviderKeyListSchema,
    WithPostHogUrl<Schemas.PaginatedLLMProviderKeyList>
> => ({
    name: 'llma-provider-key-list',
    schema: LlmaProviderKeyListSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaProviderKeyListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedLLMProviderKeyList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/provider_keys/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/ai-observability')
    },
})

const LlmaReviewQueueCreateSchema = LlmAnalyticsReviewQueuesCreateBody

const llmaReviewQueueCreate = (): ToolBase<
    typeof LlmaReviewQueueCreateSchema,
    WithPostHogUrl<Schemas.ReviewQueue>
> => ({
    name: 'llma-review-queue-create',
    schema: LlmaReviewQueueCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaReviewQueueCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        const result = await context.api.request<Schemas.ReviewQueue>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/review_queues/`,
            body,
        })
        return await withPostHogUrl(context, result, `/ai-observability/reviews?queue_id=${result.id}`)
    },
})

const LlmaReviewQueueDeleteSchema = LlmAnalyticsReviewQueuesDestroyParams.omit({ project_id: true })

const llmaReviewQueueDelete = (): ToolBase<typeof LlmaReviewQueueDeleteSchema, unknown> => ({
    name: 'llma-review-queue-delete',
    schema: LlmaReviewQueueDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaReviewQueueDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/review_queues/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const LlmaReviewQueueGetSchema = LlmAnalyticsReviewQueuesRetrieveParams.omit({ project_id: true })

const llmaReviewQueueGet = (): ToolBase<typeof LlmaReviewQueueGetSchema, WithPostHogUrl<Schemas.ReviewQueue>> => ({
    name: 'llma-review-queue-get',
    schema: LlmaReviewQueueGetSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaReviewQueueGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReviewQueue>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/review_queues/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/ai-observability/reviews?queue_id=${result.id}`)
    },
})

const LlmaReviewQueueItemCreateSchema = LlmAnalyticsReviewQueueItemsCreateBody

const llmaReviewQueueItemCreate = (): ToolBase<
    typeof LlmaReviewQueueItemCreateSchema,
    WithPostHogUrl<Schemas.ReviewQueueItem>
> => ({
    name: 'llma-review-queue-item-create',
    schema: LlmaReviewQueueItemCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaReviewQueueItemCreateSchema>) => {
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/review_queue_items/`,
            body,
        })
        return await withPostHogUrl(context, result, `/ai-observability/traces/${result.trace_id}`)
    },
})

const LlmaReviewQueueItemDeleteSchema = LlmAnalyticsReviewQueueItemsDestroyParams.omit({ project_id: true })

const llmaReviewQueueItemDelete = (): ToolBase<typeof LlmaReviewQueueItemDeleteSchema, unknown> => ({
    name: 'llma-review-queue-item-delete',
    schema: LlmaReviewQueueItemDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaReviewQueueItemDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/review_queue_items/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const LlmaReviewQueueItemGetSchema = LlmAnalyticsReviewQueueItemsRetrieveParams.omit({ project_id: true })

const llmaReviewQueueItemGet = (): ToolBase<
    typeof LlmaReviewQueueItemGetSchema,
    WithPostHogUrl<Schemas.ReviewQueueItem>
> => ({
    name: 'llma-review-queue-item-get',
    schema: LlmaReviewQueueItemGetSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaReviewQueueItemGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReviewQueueItem>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/review_queue_items/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/ai-observability/traces/${result.trace_id}`)
    },
})

const LlmaReviewQueueItemListSchema = LlmAnalyticsReviewQueueItemsListQueryParams

const llmaReviewQueueItemList = (): ToolBase<
    typeof LlmaReviewQueueItemListSchema,
    WithPostHogUrl<Schemas.PaginatedReviewQueueItemList>
> => ({
    name: 'llma-review-queue-item-list',
    schema: LlmaReviewQueueItemListSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaReviewQueueItemListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedReviewQueueItemList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/review_queue_items/`,
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
                        withPostHogUrl(context, item, `/ai-observability/traces/${item.trace_id}`)
                    )
                ),
            },
            '/ai-observability'
        )
    },
})

const LlmaReviewQueueItemUpdateSchema = LlmAnalyticsReviewQueueItemsPartialUpdateParams.omit({
    project_id: true,
}).extend(LlmAnalyticsReviewQueueItemsPartialUpdateBody.shape)

const llmaReviewQueueItemUpdate = (): ToolBase<
    typeof LlmaReviewQueueItemUpdateSchema,
    WithPostHogUrl<Schemas.ReviewQueueItem>
> => ({
    name: 'llma-review-queue-item-update',
    schema: LlmaReviewQueueItemUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaReviewQueueItemUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.queue_id !== undefined) {
            body['queue_id'] = params.queue_id
        }
        const result = await context.api.request<Schemas.ReviewQueueItem>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/review_queue_items/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/ai-observability/traces/${result.trace_id}`)
    },
})

const LlmaReviewQueueListSchema = LlmAnalyticsReviewQueuesListQueryParams

const llmaReviewQueueList = (): ToolBase<
    typeof LlmaReviewQueueListSchema,
    WithPostHogUrl<Schemas.PaginatedReviewQueueList>
> => ({
    name: 'llma-review-queue-list',
    schema: LlmaReviewQueueListSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaReviewQueueListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedReviewQueueList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/review_queues/`,
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
                        withPostHogUrl(context, item, `/ai-observability/reviews?queue_id=${item.id}`)
                    )
                ),
            },
            '/ai-observability'
        )
    },
})

const LlmaReviewQueueUpdateSchema = LlmAnalyticsReviewQueuesPartialUpdateParams.omit({ project_id: true }).extend(
    LlmAnalyticsReviewQueuesPartialUpdateBody.shape
)

const llmaReviewQueueUpdate = (): ToolBase<
    typeof LlmaReviewQueueUpdateSchema,
    WithPostHogUrl<Schemas.ReviewQueue>
> => ({
    name: 'llma-review-queue-update',
    schema: LlmaReviewQueueUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaReviewQueueUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        const result = await context.api.request<Schemas.ReviewQueue>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/review_queues/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/ai-observability/reviews?queue_id=${result.id}`)
    },
})

const LlmaScoreDefinitionCreateSchema = LlmAnalyticsScoreDefinitionsCreateBody.extend({
    config: ScoreDefinitionConfigSchema,
})

const llmaScoreDefinitionCreate = (): ToolBase<typeof LlmaScoreDefinitionCreateSchema, Schemas.ScoreDefinition> => ({
    name: 'llma-score-definition-create',
    schema: LlmaScoreDefinitionCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaScoreDefinitionCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.kind !== undefined) {
            body['kind'] = params.kind
        }
        if (params.archived !== undefined) {
            body['archived'] = params.archived
        }
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        const result = await context.api.request<Schemas.ScoreDefinition>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/score_definitions/`,
            body,
        })
        return result
    },
})

const LlmaScoreDefinitionGetSchema = LlmAnalyticsScoreDefinitionsRetrieveParams.omit({ project_id: true })

const llmaScoreDefinitionGet = (): ToolBase<typeof LlmaScoreDefinitionGetSchema, Schemas.ScoreDefinition> => ({
    name: 'llma-score-definition-get',
    schema: LlmaScoreDefinitionGetSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaScoreDefinitionGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ScoreDefinition>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/score_definitions/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const LlmaScoreDefinitionListSchema = LlmAnalyticsScoreDefinitionsListQueryParams

const llmaScoreDefinitionList = (): ToolBase<
    typeof LlmaScoreDefinitionListSchema,
    WithPostHogUrl<Schemas.PaginatedScoreDefinitionList>
> => ({
    name: 'llma-score-definition-list',
    schema: LlmaScoreDefinitionListSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaScoreDefinitionListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedScoreDefinitionList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/score_definitions/`,
            query: {
                archived: params.archived,
                kind: params.kind,
                limit: params.limit,
                offset: params.offset,
                order_by: params.order_by,
                search: params.search,
            },
        })
        return await withPostHogUrl(context, result, '/ai-observability')
    },
})

const LlmaScoreDefinitionNewVersionSchema = LlmAnalyticsScoreDefinitionsNewVersionCreateParams.omit({
    project_id: true,
})
    .extend(LlmAnalyticsScoreDefinitionsNewVersionCreateBody.shape)
    .extend({ config: ScoreDefinitionConfigSchema })

const llmaScoreDefinitionNewVersion = (): ToolBase<
    typeof LlmaScoreDefinitionNewVersionSchema,
    Schemas.ScoreDefinition
> => ({
    name: 'llma-score-definition-new-version',
    schema: LlmaScoreDefinitionNewVersionSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaScoreDefinitionNewVersionSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        if (params.base_version !== undefined) {
            body['base_version'] = params.base_version
        }
        const result = await context.api.request<Schemas.ScoreDefinition>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/score_definitions/${encodeURIComponent(String(params.id))}/new_version/`,
            body,
        })
        return result
    },
})

const LlmaScoreDefinitionUpdateSchema = LlmAnalyticsScoreDefinitionsPartialUpdateParams.omit({
    project_id: true,
}).extend(LlmAnalyticsScoreDefinitionsPartialUpdateBody.shape)

const llmaScoreDefinitionUpdate = (): ToolBase<typeof LlmaScoreDefinitionUpdateSchema, Schemas.ScoreDefinition> => ({
    name: 'llma-score-definition-update',
    schema: LlmaScoreDefinitionUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaScoreDefinitionUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.archived !== undefined) {
            body['archived'] = params.archived
        }
        const result = await context.api.request<Schemas.ScoreDefinition>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/score_definitions/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const LlmaSummarizationCreateSchema = LlmAnalyticsSummarizationCreateBody

const llmaSummarizationCreate = (): ToolBase<typeof LlmaSummarizationCreateSchema, Schemas.SummarizeResponse> => ({
    name: 'llma-summarization-create',
    schema: LlmaSummarizationCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSummarizationCreateSchema>) => {
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/summarization/`,
            body,
        })
        return result
    },
})

const LlmaTaggerCreateSchema = TaggersCreateBody

const llmaTaggerCreate = (): ToolBase<typeof LlmaTaggerCreateSchema, WithPostHogUrl<Schemas.Tagger>> => ({
    name: 'llma-tagger-create',
    schema: LlmaTaggerCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaTaggerCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.tagger_type !== undefined) {
            body['tagger_type'] = params.tagger_type
        }
        if (params.tagger_config !== undefined) {
            body['tagger_config'] = params.tagger_config
        }
        if (params.conditions !== undefined) {
            body['conditions'] = params.conditions
        }
        if (params.model_configuration !== undefined) {
            body['model_configuration'] = params.model_configuration
        }
        const result = await context.api.request<Schemas.Tagger>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/taggers/`,
            body,
        })
        return await withPostHogUrl(context, result, `/ai-evals/taggers/${result.id}`)
    },
})

const LlmaTaggerListSchema = TaggersListQueryParams

const llmaTaggerList = (): ToolBase<typeof LlmaTaggerListSchema, WithPostHogUrl<Schemas.PaginatedTaggerList>> => ({
    name: 'llma-tagger-list',
    schema: LlmaTaggerListSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaTaggerListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedTaggerList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/taggers/`,
            query: {
                enabled: params.enabled,
                id__in: Array.isArray(params.id__in) ? params.id__in.join(',') || undefined : params.id__in,
                limit: params.limit,
                offset: params.offset,
                order_by: Array.isArray(params.order_by) ? params.order_by.join(',') || undefined : params.order_by,
                search: params.search,
            },
        })
        return await withPostHogUrl(
            context,
            {
                ...result,
                results: await Promise.all(
                    (result.results ?? []).map((item) => withPostHogUrl(context, item, `/ai-evals/taggers/${item.id}`))
                ),
            },
            '/ai-evals/taggers'
        )
    },
})

const LlmaTaggerTestHogSchema = TaggersTestHogCreateBody

const llmaTaggerTestHog = (): ToolBase<typeof LlmaTaggerTestHogSchema, Schemas.TestHogTaggerResponse> => ({
    name: 'llma-tagger-test-hog',
    schema: LlmaTaggerTestHogSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaTaggerTestHogSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.source !== undefined) {
            body['source'] = params.source
        }
        if (params.sample_count !== undefined) {
            body['sample_count'] = params.sample_count
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        const result = await context.api.request<Schemas.TestHogTaggerResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/taggers/test_hog/`,
            body,
        })
        return result
    },
})

const LlmaTraceReviewCreateSchema = LlmAnalyticsTraceReviewsCreateBody

const llmaTraceReviewCreate = (): ToolBase<
    typeof LlmaTraceReviewCreateSchema,
    WithPostHogUrl<Schemas.TraceReview>
> => ({
    name: 'llma-trace-review-create',
    schema: LlmaTraceReviewCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaTraceReviewCreateSchema>) => {
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/trace_reviews/`,
            body,
        })
        return await withPostHogUrl(context, result, `/ai-observability/traces/${result.trace_id}`)
    },
})

const LlmaTraceReviewDeleteSchema = LlmAnalyticsTraceReviewsDestroyParams.omit({ project_id: true })

const llmaTraceReviewDelete = (): ToolBase<typeof LlmaTraceReviewDeleteSchema, unknown> => ({
    name: 'llma-trace-review-delete',
    schema: LlmaTraceReviewDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaTraceReviewDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/trace_reviews/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const LlmaTraceReviewGetSchema = LlmAnalyticsTraceReviewsRetrieveParams.omit({ project_id: true })

const llmaTraceReviewGet = (): ToolBase<typeof LlmaTraceReviewGetSchema, WithPostHogUrl<Schemas.TraceReview>> => ({
    name: 'llma-trace-review-get',
    schema: LlmaTraceReviewGetSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaTraceReviewGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TraceReview>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/trace_reviews/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/ai-observability/traces/${result.trace_id}`)
    },
})

const LlmaTraceReviewListSchema = LlmAnalyticsTraceReviewsListQueryParams

const llmaTraceReviewList = (): ToolBase<
    typeof LlmaTraceReviewListSchema,
    WithPostHogUrl<Schemas.PaginatedTraceReviewList>
> => ({
    name: 'llma-trace-review-list',
    schema: LlmaTraceReviewListSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaTraceReviewListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedTraceReviewList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/trace_reviews/`,
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
                        withPostHogUrl(context, item, `/ai-observability/traces/${item.trace_id}`)
                    )
                ),
            },
            '/ai-observability'
        )
    },
})

const LlmaTraceReviewUpdateSchema = LlmAnalyticsTraceReviewsPartialUpdateParams.omit({ project_id: true }).extend(
    LlmAnalyticsTraceReviewsPartialUpdateBody.shape
)

const llmaTraceReviewUpdate = (): ToolBase<
    typeof LlmaTraceReviewUpdateSchema,
    WithPostHogUrl<Schemas.TraceReview>
> => ({
    name: 'llma-trace-review-update',
    schema: LlmaTraceReviewUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaTraceReviewUpdateSchema>) => {
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_analytics/trace_reviews/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/ai-observability/traces/${result.trace_id}`)
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'llma-clustering-config-get': llmaClusteringConfigGet,
    'llma-clustering-config-set-event-filters': llmaClusteringConfigSetEventFilters,
    'llma-clustering-job-create': llmaClusteringJobCreate,
    'llma-clustering-job-delete': llmaClusteringJobDelete,
    'llma-clustering-job-get': llmaClusteringJobGet,
    'llma-clustering-job-list': llmaClusteringJobList,
    'llma-clustering-job-update': llmaClusteringJobUpdate,
    'llma-evaluation-config-get': llmaEvaluationConfigGet,
    'llma-evaluation-config-set-active-key': llmaEvaluationConfigSetActiveKey,
    'llma-evaluation-create': llmaEvaluationCreate,
    'llma-evaluation-delete': llmaEvaluationDelete,
    'llma-evaluation-get': llmaEvaluationGet,
    'llma-evaluation-judge-models': llmaEvaluationJudgeModels,
    'llma-evaluation-list': llmaEvaluationList,
    'llma-evaluation-report-create': llmaEvaluationReportCreate,
    'llma-evaluation-report-generate': llmaEvaluationReportGenerate,
    'llma-evaluation-report-get': llmaEvaluationReportGet,
    'llma-evaluation-report-list': llmaEvaluationReportList,
    'llma-evaluation-report-run-list': llmaEvaluationReportRunList,
    'llma-evaluation-report-update': llmaEvaluationReportUpdate,
    'llma-evaluation-run': llmaEvaluationRun,
    'llma-evaluation-summary-create': llmaEvaluationSummaryCreate,
    'llma-evaluation-test-hog': llmaEvaluationTestHog,
    'llma-evaluation-update': llmaEvaluationUpdate,
    'llma-personal-spend': llmaPersonalSpend,
    'llma-prompt-create': llmaPromptCreate,
    'llma-prompt-duplicate': llmaPromptDuplicate,
    'llma-prompt-get': llmaPromptGet,
    'llma-prompt-list': llmaPromptList,
    'llma-prompt-update': llmaPromptUpdate,
    'llma-provider-key-get': llmaProviderKeyGet,
    'llma-provider-key-list': llmaProviderKeyList,
    'llma-review-queue-create': llmaReviewQueueCreate,
    'llma-review-queue-delete': llmaReviewQueueDelete,
    'llma-review-queue-get': llmaReviewQueueGet,
    'llma-review-queue-item-create': llmaReviewQueueItemCreate,
    'llma-review-queue-item-delete': llmaReviewQueueItemDelete,
    'llma-review-queue-item-get': llmaReviewQueueItemGet,
    'llma-review-queue-item-list': llmaReviewQueueItemList,
    'llma-review-queue-item-update': llmaReviewQueueItemUpdate,
    'llma-review-queue-list': llmaReviewQueueList,
    'llma-review-queue-update': llmaReviewQueueUpdate,
    'llma-score-definition-create': llmaScoreDefinitionCreate,
    'llma-score-definition-get': llmaScoreDefinitionGet,
    'llma-score-definition-list': llmaScoreDefinitionList,
    'llma-score-definition-new-version': llmaScoreDefinitionNewVersion,
    'llma-score-definition-update': llmaScoreDefinitionUpdate,
    'llma-summarization-create': llmaSummarizationCreate,
    'llma-tagger-create': llmaTaggerCreate,
    'llma-tagger-list': llmaTaggerList,
    'llma-tagger-test-hog': llmaTaggerTestHog,
    'llma-trace-review-create': llmaTraceReviewCreate,
    'llma-trace-review-delete': llmaTraceReviewDelete,
    'llma-trace-review-get': llmaTraceReviewGet,
    'llma-trace-review-list': llmaTraceReviewList,
    'llma-trace-review-update': llmaTraceReviewUpdate,
}
