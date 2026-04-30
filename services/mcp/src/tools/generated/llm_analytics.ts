// AUTO-GENERATED from products/llm_analytics/mcp/tools.yaml + OpenAPI — do not edit
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
    LlmAnalyticsClusteringJobsListQueryParams,
    LlmAnalyticsClusteringJobsRetrieveParams,
    LlmAnalyticsEvaluationConfigSetActiveKeyCreateBody,
    LlmAnalyticsEvaluationReportsCreateBody,
    LlmAnalyticsEvaluationReportsDestroyParams,
    LlmAnalyticsEvaluationReportsGenerateCreateParams,
    LlmAnalyticsEvaluationReportsListQueryParams,
    LlmAnalyticsEvaluationReportsPartialUpdateBody,
    LlmAnalyticsEvaluationReportsPartialUpdateParams,
    LlmAnalyticsEvaluationReportsRetrieveParams,
    LlmAnalyticsEvaluationReportsRunsListParams,
    LlmAnalyticsEvaluationReportsRunsListQueryParams,
    LlmAnalyticsEvaluationSummaryCreateBody,
    LlmAnalyticsModelsRetrieveQueryParams,
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
    LlmPromptsCreateBody,
    LlmPromptsNameDuplicateCreateBody,
    LlmPromptsNameDuplicateCreateParams,
    LlmPromptsNamePartialUpdateBody,
    LlmPromptsNamePartialUpdateParams,
    LlmPromptsNameRetrieveParams,
    LlmPromptsNameRetrieveQueryParams,
    LlmSkillsCreateBody,
    LlmSkillsListQueryParams,
    LlmSkillsNameDuplicateCreateBody,
    LlmSkillsNameDuplicateCreateParams,
    LlmSkillsNameFilesCreateBody,
    LlmSkillsNameFilesCreateParams,
    LlmSkillsNameFilesDestroyParams,
    LlmSkillsNameFilesDestroyQueryParams,
    LlmSkillsNameFilesRenameCreateBody,
    LlmSkillsNameFilesRenameCreateParams,
    LlmSkillsNameFilesRetrieveParams,
    LlmSkillsNameFilesRetrieveQueryParams,
    LlmSkillsNamePartialUpdateBody,
    LlmSkillsNamePartialUpdateParams,
    LlmSkillsNameRetrieveParams,
    LlmSkillsNameRetrieveQueryParams,
} from '@/generated/llm_analytics/api'
import { PromptListInputSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const LlmaClusteringJobGetSchema = LlmAnalyticsClusteringJobsRetrieveParams.omit({ project_id: true })

const llmaClusteringJobGet = (): ToolBase<typeof LlmaClusteringJobGetSchema, Schemas.ClusteringJob> => ({
    name: 'llma-clustering-job-get',
    schema: LlmaClusteringJobGetSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaClusteringJobGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ClusteringJob>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/clustering_jobs/${encodeURIComponent(String(params.id))}/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/clustering_jobs/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_config/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_config/set_active_key/`,
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
        if (params.model_configuration !== undefined) {
            body['model_configuration'] = params.model_configuration
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        const result = await context.api.request<Schemas.Evaluation>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/evaluations/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/evaluations/${encodeURIComponent(String(params.id))}/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/evaluations/${encodeURIComponent(String(params.id))}/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/models/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/evaluations/`,
            query: {
                enabled: params.enabled,
                id__in: params.id__in,
                limit: params.limit,
                offset: params.offset,
                order_by: params.order_by,
                search: params.search,
            },
        })
        return result
    },
})

const LlmaEvaluationReportCreateSchema = LlmAnalyticsEvaluationReportsCreateBody.omit({ deleted: true })

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
        if (params.starts_at !== undefined) {
            body['starts_at'] = params.starts_at
        }
        if (params.timezone_name !== undefined) {
            body['timezone_name'] = params.timezone_name
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_reports/`,
            body,
        })
        return result
    },
})

const LlmaEvaluationReportDeleteSchema = LlmAnalyticsEvaluationReportsDestroyParams.omit({ project_id: true })

const llmaEvaluationReportDelete = (): ToolBase<typeof LlmaEvaluationReportDeleteSchema, Schemas.EvaluationReport> => ({
    name: 'llma-evaluation-report-delete',
    schema: LlmaEvaluationReportDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaEvaluationReportDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.EvaluationReport>({
            method: 'PATCH',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_reports/${encodeURIComponent(String(params.id))}/`,
            body: { deleted: true },
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_reports/${encodeURIComponent(String(params.id))}/generate/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_reports/${encodeURIComponent(String(params.id))}/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_reports/`,
            query: {
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_reports/${encodeURIComponent(String(params.id))}/runs/`,
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

const llmaEvaluationReportUpdate = (): ToolBase<typeof LlmaEvaluationReportUpdateSchema, Schemas.EvaluationReport> => ({
    name: 'llma-evaluation-report-update',
    schema: LlmaEvaluationReportUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaEvaluationReportUpdateSchema>) => {
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
        if (params.starts_at !== undefined) {
            body['starts_at'] = params.starts_at
        }
        if (params.timezone_name !== undefined) {
            body['timezone_name'] = params.timezone_name
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
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
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
            method: 'PATCH',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_reports/${encodeURIComponent(String(params.id))}/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/evaluation_runs/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_summary/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/evaluations/test_hog/`,
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
        if (params.model_configuration !== undefined) {
            body['model_configuration'] = params.model_configuration
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        const result = await context.api.request<Schemas.Evaluation>({
            method: 'PATCH',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/evaluations/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const LlmaPromptCreateSchema = LlmPromptsCreateBody

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
        const result = await context.api.request<Schemas.LLMPrompt>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_prompts/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_prompts/name/${encodeURIComponent(String(params.prompt_name))}/duplicate/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_prompts/name/${encodeURIComponent(String(params.prompt_name))}/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_prompts/`,
            query: parsedParams,
        })
        return result
    },
})

const LlmaPromptUpdateSchema = LlmPromptsNamePartialUpdateParams.omit({ project_id: true }).extend(
    LlmPromptsNamePartialUpdateBody.shape
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
        const result = await context.api.request<Schemas.LLMPrompt>({
            method: 'PATCH',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_prompts/name/${encodeURIComponent(String(params.prompt_name))}/`,
            body,
        })
        return result
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/review_queues/`,
            body,
        })
        return await withPostHogUrl(context, result, `/llm-analytics/reviews?queue_id=${result.id}`)
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/review_queues/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const LlmaReviewQueueGetSchema = LlmAnalyticsReviewQueuesRetrieveParams.omit({ project_id: true })

const llmaReviewQueueGet = (): ToolBase<typeof LlmaReviewQueueGetSchema, WithPostHogUrl<Schemas.ReviewQueue>> => ({
    name: 'llma-review-queue-get',
    schema: LlmaReviewQueueGetSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof LlmaReviewQueueGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReviewQueue>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/review_queues/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/llm-analytics/reviews?queue_id=${result.id}`)
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/review_queue_items/`,
            body,
        })
        return await withPostHogUrl(context, result, `/llm-analytics/traces/${result.trace_id}`)
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/review_queue_items/${encodeURIComponent(String(params.id))}/`,
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
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof LlmaReviewQueueItemGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReviewQueueItem>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/review_queue_items/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/llm-analytics/traces/${result.trace_id}`)
    },
})

const LlmaReviewQueueItemListSchema = LlmAnalyticsReviewQueueItemsListQueryParams

const llmaReviewQueueItemList = (): ToolBase<
    typeof LlmaReviewQueueItemListSchema,
    WithPostHogUrl<Schemas.PaginatedReviewQueueItemList>
> => ({
    name: 'llma-review-queue-item-list',
    schema: LlmaReviewQueueItemListSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof LlmaReviewQueueItemListSchema>) => {
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/review_queue_items/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/llm-analytics/traces/${result.trace_id}`)
    },
})

const LlmaReviewQueueListSchema = LlmAnalyticsReviewQueuesListQueryParams

const llmaReviewQueueList = (): ToolBase<
    typeof LlmaReviewQueueListSchema,
    WithPostHogUrl<Schemas.PaginatedReviewQueueList>
> => ({
    name: 'llma-review-queue-list',
    schema: LlmaReviewQueueListSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof LlmaReviewQueueListSchema>) => {
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/review_queues/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/llm-analytics/reviews?queue_id=${result.id}`)
    },
})

const LlmaSentimentCreateSchema = LlmAnalyticsSentimentCreateBody

const llmaSentimentCreate = (): ToolBase<typeof LlmaSentimentCreateSchema, Schemas.SentimentBatchResponse> => ({
    name: 'llma-sentiment-create',
    schema: LlmaSentimentCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSentimentCreateSchema>) => {
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

const LlmaSkillCreateSchema = LlmSkillsCreateBody

const llmaSkillCreate = (): ToolBase<typeof LlmaSkillCreateSchema, Schemas.LLMSkillCreate> => ({
    name: 'llma-skill-create',
    schema: LlmaSkillCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSkillCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.body !== undefined) {
            body['body'] = params.body
        }
        if (params.license !== undefined) {
            body['license'] = params.license
        }
        if (params.compatibility !== undefined) {
            body['compatibility'] = params.compatibility
        }
        if (params.allowed_tools !== undefined) {
            body['allowed_tools'] = params.allowed_tools
        }
        if (params.metadata !== undefined) {
            body['metadata'] = params.metadata
        }
        if (params.files !== undefined) {
            body['files'] = params.files
        }
        const result = await context.api.request<Schemas.LLMSkillCreate>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_skills/`,
            body,
        })
        return result
    },
})

const LlmaSkillDuplicateSchema = LlmSkillsNameDuplicateCreateParams.omit({ project_id: true }).extend(
    LlmSkillsNameDuplicateCreateBody.shape
)

const llmaSkillDuplicate = (): ToolBase<typeof LlmaSkillDuplicateSchema, Schemas.LLMSkill> => ({
    name: 'llma-skill-duplicate',
    schema: LlmaSkillDuplicateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSkillDuplicateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.new_name !== undefined) {
            body['new_name'] = params.new_name
        }
        const result = await context.api.request<Schemas.LLMSkill>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/duplicate/`,
            body,
        })
        return result
    },
})

const LlmaSkillFileCreateSchema = LlmSkillsNameFilesCreateParams.omit({ project_id: true }).extend(
    LlmSkillsNameFilesCreateBody.shape
)

const llmaSkillFileCreate = (): ToolBase<typeof LlmaSkillFileCreateSchema, Schemas.LLMSkill> => ({
    name: 'llma-skill-file-create',
    schema: LlmaSkillFileCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSkillFileCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.path !== undefined) {
            body['path'] = params.path
        }
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        if (params.content_type !== undefined) {
            body['content_type'] = params.content_type
        }
        if (params.base_version !== undefined) {
            body['base_version'] = params.base_version
        }
        const result = await context.api.request<Schemas.LLMSkill>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/files/`,
            body,
        })
        return result
    },
})

const LlmaSkillFileDeleteSchema = LlmSkillsNameFilesDestroyParams.omit({ project_id: true }).extend(
    LlmSkillsNameFilesDestroyQueryParams.shape
)

const llmaSkillFileDelete = (): ToolBase<typeof LlmaSkillFileDeleteSchema, Schemas.LLMSkill> => ({
    name: 'llma-skill-file-delete',
    schema: LlmaSkillFileDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSkillFileDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LLMSkill>({
            method: 'DELETE',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/files/${encodeURIComponent(String(params.file_path))}/`,
            query: {
                base_version: params.base_version,
            },
        })
        return result
    },
})

const LlmaSkillFileGetSchema = LlmSkillsNameFilesRetrieveParams.omit({ project_id: true }).extend(
    LlmSkillsNameFilesRetrieveQueryParams.shape
)

const llmaSkillFileGet = (): ToolBase<typeof LlmaSkillFileGetSchema, Schemas.LLMSkillFile> => ({
    name: 'llma-skill-file-get',
    schema: LlmaSkillFileGetSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSkillFileGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LLMSkillFile>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/files/${encodeURIComponent(String(params.file_path))}/`,
            query: {
                version: params.version,
            },
        })
        return result
    },
})

const LlmaSkillFileRenameSchema = LlmSkillsNameFilesRenameCreateParams.omit({ project_id: true }).extend(
    LlmSkillsNameFilesRenameCreateBody.shape
)

const llmaSkillFileRename = (): ToolBase<typeof LlmaSkillFileRenameSchema, Schemas.LLMSkill> => ({
    name: 'llma-skill-file-rename',
    schema: LlmaSkillFileRenameSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSkillFileRenameSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.old_path !== undefined) {
            body['old_path'] = params.old_path
        }
        if (params.new_path !== undefined) {
            body['new_path'] = params.new_path
        }
        if (params.base_version !== undefined) {
            body['base_version'] = params.base_version
        }
        const result = await context.api.request<Schemas.LLMSkill>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/files-rename/`,
            body,
        })
        return result
    },
})

const LlmaSkillGetSchema = LlmSkillsNameRetrieveParams.omit({ project_id: true }).extend(
    LlmSkillsNameRetrieveQueryParams.shape
)

const llmaSkillGet = (): ToolBase<typeof LlmaSkillGetSchema, Schemas.LLMSkill> => ({
    name: 'llma-skill-get',
    schema: LlmaSkillGetSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSkillGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LLMSkill>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/`,
            query: {
                version: params.version,
            },
        })
        return result
    },
})

const LlmaSkillListSchema = LlmSkillsListQueryParams

const llmaSkillList = (): ToolBase<typeof LlmaSkillListSchema, Schemas.PaginatedLLMSkillListList> => ({
    name: 'llma-skill-list',
    schema: LlmaSkillListSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSkillListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedLLMSkillListList>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_skills/`,
            query: {
                created_by_id: params.created_by_id,
                limit: params.limit,
                offset: params.offset,
                search: params.search,
            },
        })
        return result
    },
})

const LlmaSkillUpdateSchema = LlmSkillsNamePartialUpdateParams.omit({ project_id: true }).extend(
    LlmSkillsNamePartialUpdateBody.shape
)

const llmaSkillUpdate = (): ToolBase<typeof LlmaSkillUpdateSchema, Schemas.LLMSkill> => ({
    name: 'llma-skill-update',
    schema: LlmaSkillUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSkillUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.body !== undefined) {
            body['body'] = params.body
        }
        if (params.edits !== undefined) {
            body['edits'] = params.edits
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.license !== undefined) {
            body['license'] = params.license
        }
        if (params.compatibility !== undefined) {
            body['compatibility'] = params.compatibility
        }
        if (params.allowed_tools !== undefined) {
            body['allowed_tools'] = params.allowed_tools
        }
        if (params.metadata !== undefined) {
            body['metadata'] = params.metadata
        }
        if (params.files !== undefined) {
            body['files'] = params.files
        }
        if (params.file_edits !== undefined) {
            body['file_edits'] = params.file_edits
        }
        if (params.base_version !== undefined) {
            body['base_version'] = params.base_version
        }
        const result = await context.api.request<Schemas.LLMSkill>({
            method: 'PATCH',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/summarization/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/trace_reviews/`,
            body,
        })
        return await withPostHogUrl(context, result, `/llm-analytics/traces/${result.trace_id}`)
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/trace_reviews/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const LlmaTraceReviewGetSchema = LlmAnalyticsTraceReviewsRetrieveParams.omit({ project_id: true })

const llmaTraceReviewGet = (): ToolBase<typeof LlmaTraceReviewGetSchema, WithPostHogUrl<Schemas.TraceReview>> => ({
    name: 'llma-trace-review-get',
    schema: LlmaTraceReviewGetSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof LlmaTraceReviewGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TraceReview>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/trace_reviews/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/llm-analytics/traces/${result.trace_id}`)
    },
})

const LlmaTraceReviewListSchema = LlmAnalyticsTraceReviewsListQueryParams

const llmaTraceReviewList = (): ToolBase<
    typeof LlmaTraceReviewListSchema,
    WithPostHogUrl<Schemas.PaginatedTraceReviewList>
> => ({
    name: 'llma-trace-review-list',
    schema: LlmaTraceReviewListSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof LlmaTraceReviewListSchema>) => {
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/trace_reviews/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/llm-analytics/traces/${result.trace_id}`)
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'llma-clustering-job-get': llmaClusteringJobGet,
    'llma-clustering-job-list': llmaClusteringJobList,
    'llma-evaluation-config-get': llmaEvaluationConfigGet,
    'llma-evaluation-config-set-active-key': llmaEvaluationConfigSetActiveKey,
    'llma-evaluation-create': llmaEvaluationCreate,
    'llma-evaluation-delete': llmaEvaluationDelete,
    'llma-evaluation-get': llmaEvaluationGet,
    'llma-evaluation-judge-models': llmaEvaluationJudgeModels,
    'llma-evaluation-list': llmaEvaluationList,
    'llma-evaluation-report-create': llmaEvaluationReportCreate,
    'llma-evaluation-report-delete': llmaEvaluationReportDelete,
    'llma-evaluation-report-generate': llmaEvaluationReportGenerate,
    'llma-evaluation-report-get': llmaEvaluationReportGet,
    'llma-evaluation-report-list': llmaEvaluationReportList,
    'llma-evaluation-report-run-list': llmaEvaluationReportRunList,
    'llma-evaluation-report-update': llmaEvaluationReportUpdate,
    'llma-evaluation-run': llmaEvaluationRun,
    'llma-evaluation-summary-create': llmaEvaluationSummaryCreate,
    'llma-evaluation-test-hog': llmaEvaluationTestHog,
    'llma-evaluation-update': llmaEvaluationUpdate,
    'llma-prompt-create': llmaPromptCreate,
    'llma-prompt-duplicate': llmaPromptDuplicate,
    'llma-prompt-get': llmaPromptGet,
    'llma-prompt-list': llmaPromptList,
    'llma-prompt-update': llmaPromptUpdate,
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
    'llma-sentiment-create': llmaSentimentCreate,
    'llma-skill-create': llmaSkillCreate,
    'llma-skill-duplicate': llmaSkillDuplicate,
    'llma-skill-file-create': llmaSkillFileCreate,
    'llma-skill-file-delete': llmaSkillFileDelete,
    'llma-skill-file-get': llmaSkillFileGet,
    'llma-skill-file-rename': llmaSkillFileRename,
    'llma-skill-get': llmaSkillGet,
    'llma-skill-list': llmaSkillList,
    'llma-skill-update': llmaSkillUpdate,
    'llma-summarization-create': llmaSummarizationCreate,
    'llma-trace-review-create': llmaTraceReviewCreate,
    'llma-trace-review-delete': llmaTraceReviewDelete,
    'llma-trace-review-get': llmaTraceReviewGet,
    'llma-trace-review-list': llmaTraceReviewList,
    'llma-trace-review-update': llmaTraceReviewUpdate,
}
