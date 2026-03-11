// AUTO-GENERATED from products/llm_analytics/mcp/evaluations.yaml + OpenAPI — do not edit
import { z } from 'zod'

import {
    EvaluationRunsCreateBody,
    EvaluationsCreateBody,
    EvaluationsListQueryParams,
    EvaluationsPartialUpdateBody,
    EvaluationsPartialUpdateParams,
    EvaluationsRetrieveParams,
} from '@/generated/evaluations/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const EvaluationsListSchema = EvaluationsListQueryParams.omit({ enabled: true, id__in: true, order_by: true })

const evaluationsList = (): ToolBase<typeof EvaluationsListSchema> => ({
    name: 'evaluations-list',
    schema: EvaluationsListSchema,
    handler: async (context: Context, params: z.infer<typeof EvaluationsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request({
            method: 'GET',
            path: `/api/environments/${projectId}/evaluations/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                search: params.search,
            },
        })
        return result
    },
})

const EvaluationsCreateSchema = EvaluationsCreateBody

const evaluationsCreate = (): ToolBase<typeof EvaluationsCreateSchema> => ({
    name: 'evaluations-create',
    schema: EvaluationsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof EvaluationsCreateSchema>) => {
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
        const result = await context.api.request({
            method: 'POST',
            path: `/api/environments/${projectId}/evaluations/`,
            body,
        })
        return {
            ...(result as any),
            url: `${context.api.getProjectBaseUrl(projectId)}/evaluations/${(result as any).id}`,
        }
    },
})

const EvaluationsRetrieveSchema = EvaluationsRetrieveParams.omit({ project_id: true })

const evaluationsRetrieve = (): ToolBase<typeof EvaluationsRetrieveSchema> => ({
    name: 'evaluations-retrieve',
    schema: EvaluationsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof EvaluationsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request({
            method: 'GET',
            path: `/api/environments/${projectId}/evaluations/${params.id}/`,
        })
        return result
    },
})

const EvaluationsPartialUpdateSchema = EvaluationsPartialUpdateParams.omit({ project_id: true }).extend(
    EvaluationsPartialUpdateBody.shape
)

const evaluationsPartialUpdate = (): ToolBase<typeof EvaluationsPartialUpdateSchema> => ({
    name: 'evaluations-partial-update',
    schema: EvaluationsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof EvaluationsPartialUpdateSchema>) => {
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
        const result = await context.api.request({
            method: 'PATCH',
            path: `/api/environments/${projectId}/evaluations/${params.id}/`,
            body,
        })
        return result
    },
})

const EvaluationRunSchema = EvaluationRunsCreateBody

const evaluationRun = (): ToolBase<typeof EvaluationRunSchema> => ({
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
        const result = await context.api.request({
            method: 'POST',
            path: `/api/environments/${projectId}/evaluation_runs/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'evaluations-list': evaluationsList,
    'evaluations-create': evaluationsCreate,
    'evaluations-retrieve': evaluationsRetrieve,
    'evaluations-partial-update': evaluationsPartialUpdate,
    'evaluation-run': evaluationRun,
}
