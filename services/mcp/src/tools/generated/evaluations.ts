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
    LlmAnalyticsEvaluationConfigSetActiveKeyCreateBody,
    LlmAnalyticsModelsRetrieveQueryParams,
} from '@/generated/evaluations/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const EvaluationConfigGetSchema = z.object({})

const evaluationConfigGet = (): ToolBase<typeof EvaluationConfigGetSchema, Schemas.EvaluationConfig> => ({
    name: 'evaluation-config-get',
    schema: EvaluationConfigGetSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof EvaluationConfigGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.EvaluationConfig>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_analytics/evaluation_config/`,
        })
        return result
    },
})

const EvaluationConfigSetActiveKeySchema = LlmAnalyticsEvaluationConfigSetActiveKeyCreateBody

const evaluationConfigSetActiveKey = (): ToolBase<
    typeof EvaluationConfigSetActiveKeySchema,
    Schemas.EvaluationConfig
> => ({
    name: 'evaluation-config-set-active-key',
    schema: EvaluationConfigSetActiveKeySchema,
    handler: async (context: Context, params: z.infer<typeof EvaluationConfigSetActiveKeySchema>) => {
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

const EvaluationJudgeModelsSchema = LlmAnalyticsModelsRetrieveQueryParams

const evaluationJudgeModels = (): ToolBase<typeof EvaluationJudgeModelsSchema, Schemas.LLMModelsListResponse> => ({
    name: 'evaluation-judge-models',
    schema: EvaluationJudgeModelsSchema,
    handler: async (context: Context, params: z.infer<typeof EvaluationJudgeModelsSchema>) => {
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
    'evaluation-config-get': evaluationConfigGet,
    'evaluation-config-set-active-key': evaluationConfigSetActiveKey,
    'evaluation-create': evaluationCreate,
    'evaluation-delete': evaluationDelete,
    'evaluation-get': evaluationGet,
    'evaluation-judge-models': evaluationJudgeModels,
    'evaluation-run': evaluationRun,
    'evaluation-test-hog': evaluationTestHog,
    'evaluation-update': evaluationUpdate,
    'evaluations-get': evaluationsGet,
}
