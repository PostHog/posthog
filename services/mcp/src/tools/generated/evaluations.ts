// AUTO-GENERATED from products/llm_analytics/mcp/evaluations.yaml + OpenAPI — do not edit
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
    LlmAnalyticsEvaluationReportsGenerateCreateParams,
    LlmAnalyticsEvaluationReportsListQueryParams,
    LlmAnalyticsEvaluationReportsPartialUpdateBody,
    LlmAnalyticsEvaluationReportsPartialUpdateParams,
    LlmAnalyticsEvaluationReportsRetrieveParams,
    LlmAnalyticsEvaluationReportsRunsListParams,
    LlmAnalyticsEvaluationReportsRunsListQueryParams,
} from '@/generated/evaluations/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const EvaluationCreateSchema = EvaluationsCreateBody

const evaluationCreate = (): ToolBase<typeof EvaluationCreateSchema, Schemas.Evaluation> => ({
    name: 'evaluation-create',
    schema: EvaluationCreateSchema,
    handler: async (context: Context, params: z.infer<typeof EvaluationCreateSchema>) => {
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

const EvaluationDeleteSchema = EvaluationsDestroyParams.omit({ project_id: true })

const evaluationDelete = (): ToolBase<typeof EvaluationDeleteSchema, Schemas.Evaluation> => ({
    name: 'evaluation-delete',
    schema: EvaluationDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof EvaluationDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Evaluation>({
            method: 'PATCH',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/evaluations/${encodeURIComponent(String(params.id))}/`,
            body: { deleted: true },
        })
        return result
    },
})

const EvaluationGetSchema = EvaluationsRetrieveParams.omit({ project_id: true })

const evaluationGet = (): ToolBase<typeof EvaluationGetSchema, Schemas.Evaluation> => ({
    name: 'evaluation-get',
    schema: EvaluationGetSchema,
    handler: async (context: Context, params: z.infer<typeof EvaluationGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Evaluation>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/evaluations/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const EvaluationReportGenerateSchema = LlmAnalyticsEvaluationReportsGenerateCreateParams.omit({ project_id: true })

const evaluationReportGenerate = (): ToolBase<typeof EvaluationReportGenerateSchema, unknown> => ({
    name: 'evaluation-report-generate',
    schema: EvaluationReportGenerateSchema,
    handler: async (context: Context, params: z.infer<typeof EvaluationReportGenerateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_reports/${encodeURIComponent(String(params.id))}/generate/`,
        })
        return result
    },
})

const EvaluationReportGetSchema = LlmAnalyticsEvaluationReportsRetrieveParams.omit({ project_id: true })

const evaluationReportGet = (): ToolBase<typeof EvaluationReportGetSchema, Schemas.EvaluationReport> => ({
    name: 'evaluation-report-get',
    schema: EvaluationReportGetSchema,
    handler: async (context: Context, params: z.infer<typeof EvaluationReportGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.EvaluationReport>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_reports/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const EvaluationReportRunsListSchema = LlmAnalyticsEvaluationReportsRunsListParams.omit({ project_id: true }).extend(
    LlmAnalyticsEvaluationReportsRunsListQueryParams.shape
)

const evaluationReportRunsList = (): ToolBase<
    typeof EvaluationReportRunsListSchema,
    Schemas.PaginatedEvaluationReportRunList
> => ({
    name: 'evaluation-report-runs-list',
    schema: EvaluationReportRunsListSchema,
    handler: async (context: Context, params: z.infer<typeof EvaluationReportRunsListSchema>) => {
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

const EvaluationReportUpdateSchema = LlmAnalyticsEvaluationReportsPartialUpdateParams.omit({ project_id: true }).extend(
    LlmAnalyticsEvaluationReportsPartialUpdateBody.shape
)

const evaluationReportUpdate = (): ToolBase<typeof EvaluationReportUpdateSchema, Schemas.EvaluationReport> => ({
    name: 'evaluation-report-update',
    schema: EvaluationReportUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof EvaluationReportUpdateSchema>) => {
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

const EvaluationReportsListSchema = LlmAnalyticsEvaluationReportsListQueryParams

const evaluationReportsList = (): ToolBase<
    typeof EvaluationReportsListSchema,
    Schemas.PaginatedEvaluationReportList
> => ({
    name: 'evaluation-reports-list',
    schema: EvaluationReportsListSchema,
    handler: async (context: Context, params: z.infer<typeof EvaluationReportsListSchema>) => {
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

const EvaluationRunSchema = EvaluationRunsCreateBody

const evaluationRun = (): ToolBase<typeof EvaluationRunSchema, unknown> => ({
    name: 'evaluation-run',
    schema: EvaluationRunSchema,
    handler: async (context: Context, params: z.infer<typeof EvaluationRunSchema>) => {
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

const EvaluationTestHogSchema = EvaluationsTestHogCreateBody

const evaluationTestHog = (): ToolBase<typeof EvaluationTestHogSchema, Schemas.TestHogResponse> => ({
    name: 'evaluation-test-hog',
    schema: EvaluationTestHogSchema,
    handler: async (context: Context, params: z.infer<typeof EvaluationTestHogSchema>) => {
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

const EvaluationUpdateSchema = EvaluationsPartialUpdateParams.omit({ project_id: true }).extend(
    EvaluationsPartialUpdateBody.shape
)

const evaluationUpdate = (): ToolBase<typeof EvaluationUpdateSchema, Schemas.Evaluation> => ({
    name: 'evaluation-update',
    schema: EvaluationUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof EvaluationUpdateSchema>) => {
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

const EvaluationsGetSchema = EvaluationsListQueryParams

const evaluationsGet = (): ToolBase<typeof EvaluationsGetSchema, Schemas.PaginatedEvaluationList> => ({
    name: 'evaluations-get',
    schema: EvaluationsGetSchema,
    handler: async (context: Context, params: z.infer<typeof EvaluationsGetSchema>) => {
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

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'evaluation-create': evaluationCreate,
    'evaluation-delete': evaluationDelete,
    'evaluation-get': evaluationGet,
    'evaluation-report-generate': evaluationReportGenerate,
    'evaluation-report-get': evaluationReportGet,
    'evaluation-report-runs-list': evaluationReportRunsList,
    'evaluation-report-update': evaluationReportUpdate,
    'evaluation-reports-list': evaluationReportsList,
    'evaluation-run': evaluationRun,
    'evaluation-test-hog': evaluationTestHog,
    'evaluation-update': evaluationUpdate,
    'evaluations-get': evaluationsGet,
}
