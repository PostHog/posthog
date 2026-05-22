// AUTO-GENERATED from products/ai_observability/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    EvaluationRunsCreateBody,
    EvaluationsCreateBody,
    EvaluationsListQueryParams,
    EvaluationsTestHogCreateBody,
    LlmAnalyticsClusteringJobsListQueryParams,
    LlmAnalyticsEvaluationConfigSetActiveKeyCreateBody,
    LlmAnalyticsEvaluationReportsCreateBody,
    LlmAnalyticsEvaluationReportsListQueryParams,
    LlmAnalyticsEvaluationSummaryCreateBody,
    LlmAnalyticsModelsRetrieveQueryParams,
    LlmAnalyticsPersonalSpendListQueryParams,
    LlmAnalyticsReviewQueueItemsCreateBody,
    LlmAnalyticsReviewQueueItemsListQueryParams,
    LlmAnalyticsReviewQueuesCreateBody,
    LlmAnalyticsReviewQueuesListQueryParams,
    LlmAnalyticsScoreDefinitionsCreateBody,
    LlmAnalyticsScoreDefinitionsListQueryParams,
    LlmAnalyticsSentimentCreateBody,
    LlmAnalyticsSummarizationCreateBody,
    LlmAnalyticsTraceReviewsCreateBody,
    LlmAnalyticsTraceReviewsListQueryParams,
    LlmSkillsCreateBody,
    LlmSkillsListQueryParams,
    LlmSkillsNameArchiveCreateParams,
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
    TaggersCreateBody,
    TaggersListQueryParams,
    TaggersTestHogCreateBody,
} from '@/generated/ai_observability/api'
import { ScoreDefinitionConfigSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/review_queue_items/`,
            body,
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
                        withPostHogUrl(context, item, `/ai-observability/traces/${item.trace_id}`)
                    )
                ),
            },
            '/ai-observability'
        )
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
                        withPostHogUrl(context, item, `/ai-observability/reviews?queue_id=${item.id}`)
                    )
                ),
            },
            '/ai-observability'
        )
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/score_definitions/`,
            body,
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
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof LlmaScoreDefinitionListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedScoreDefinitionList>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/score_definitions/`,
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

const LlmaSkillArchiveSchema = LlmSkillsNameArchiveCreateParams.omit({ project_id: true }).extend({
    skill_name: LlmSkillsNameArchiveCreateParams.shape['skill_name'].describe(
        'The kebab-case name of the skill to archive.'
    ),
})

const llmaSkillArchive = (): ToolBase<typeof LlmaSkillArchiveSchema, unknown> => ({
    name: 'llma-skill-archive',
    schema: LlmaSkillArchiveSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSkillArchiveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/archive/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/taggers/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/taggers/`,
            query: {
                enabled: params.enabled,
                id__in: params.id__in,
                limit: params.limit,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/taggers/test_hog/`,
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
                        withPostHogUrl(context, item, `/ai-observability/traces/${item.trace_id}`)
                    )
                ),
            },
            '/ai-observability'
        )
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'llma-clustering-job-list': llmaClusteringJobList,
    'llma-evaluation-config-get': llmaEvaluationConfigGet,
    'llma-evaluation-config-set-active-key': llmaEvaluationConfigSetActiveKey,
    'llma-evaluation-create': llmaEvaluationCreate,
    'llma-evaluation-judge-models': llmaEvaluationJudgeModels,
    'llma-evaluation-list': llmaEvaluationList,
    'llma-evaluation-report-create': llmaEvaluationReportCreate,
    'llma-evaluation-report-list': llmaEvaluationReportList,
    'llma-evaluation-run': llmaEvaluationRun,
    'llma-evaluation-summary-create': llmaEvaluationSummaryCreate,
    'llma-evaluation-test-hog': llmaEvaluationTestHog,
    'llma-personal-spend': llmaPersonalSpend,
    'llma-review-queue-create': llmaReviewQueueCreate,
    'llma-review-queue-item-create': llmaReviewQueueItemCreate,
    'llma-review-queue-item-list': llmaReviewQueueItemList,
    'llma-review-queue-list': llmaReviewQueueList,
    'llma-score-definition-create': llmaScoreDefinitionCreate,
    'llma-score-definition-list': llmaScoreDefinitionList,
    'llma-sentiment-create': llmaSentimentCreate,
    'llma-skill-archive': llmaSkillArchive,
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
    'llma-tagger-create': llmaTaggerCreate,
    'llma-tagger-list': llmaTaggerList,
    'llma-tagger-test-hog': llmaTaggerTestHog,
    'llma-trace-review-create': llmaTraceReviewCreate,
    'llma-trace-review-list': llmaTraceReviewList,
}
