// AUTO-GENERATED from products/llm_analytics/mcp/evaluation_reports.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    LlmAnalyticsEvaluationReportsCreateBody,
    LlmAnalyticsEvaluationReportsDestroyParams,
    LlmAnalyticsEvaluationReportsGenerateCreateParams,
    LlmAnalyticsEvaluationReportsListQueryParams,
    LlmAnalyticsEvaluationReportsPartialUpdateBody,
    LlmAnalyticsEvaluationReportsPartialUpdateParams,
    LlmAnalyticsEvaluationReportsRetrieveParams,
    LlmAnalyticsEvaluationReportsRunsListParams,
    LlmAnalyticsEvaluationReportsRunsListQueryParams,
} from '@/generated/evaluation_reports/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const EvaluationReportCreateSchema = LlmAnalyticsEvaluationReportsCreateBody.omit({ deleted: true })

const evaluationReportCreate = (): ToolBase<typeof EvaluationReportCreateSchema, Schemas.EvaluationReport> => ({
    name: 'evaluation-report-create',
    schema: EvaluationReportCreateSchema,
    handler: async (context: Context, params: z.infer<typeof EvaluationReportCreateSchema>) => {
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

const EvaluationReportDeleteSchema = LlmAnalyticsEvaluationReportsDestroyParams.omit({ project_id: true })

const evaluationReportDelete = (): ToolBase<typeof EvaluationReportDeleteSchema, Schemas.EvaluationReport> => ({
    name: 'evaluation-report-delete',
    schema: EvaluationReportDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof EvaluationReportDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.EvaluationReport>({
            method: 'PATCH',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_reports/${encodeURIComponent(String(params.id))}/`,
            body: { deleted: true },
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

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'evaluation-report-create': evaluationReportCreate,
    'evaluation-report-delete': evaluationReportDelete,
    'evaluation-report-generate': evaluationReportGenerate,
    'evaluation-report-get': evaluationReportGet,
    'evaluation-report-runs-list': evaluationReportRunsList,
    'evaluation-report-update': evaluationReportUpdate,
    'evaluation-reports-list': evaluationReportsList,
}
