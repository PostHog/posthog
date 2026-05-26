// AUTO-GENERATED from products/autoresearch/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    AutoresearchArchiveCreateBody,
    AutoresearchArchiveCreateParams,
    AutoresearchCreateBody,
    AutoresearchListQueryParams,
    AutoresearchModelsListParams,
    AutoresearchModelsListQueryParams,
    AutoresearchModelsRetrieveParams,
    AutoresearchPauseCreateBody,
    AutoresearchPauseCreateParams,
    AutoresearchResumeCreateBody,
    AutoresearchResumeCreateParams,
    AutoresearchRetrieveParams,
    AutoresearchRunsListParams,
    AutoresearchRunsListQueryParams,
    AutoresearchScoreCreateParams,
    AutoresearchTrainCreateBody,
    AutoresearchTrainCreateParams,
    AutoresearchTrainingRunsListParams,
    AutoresearchTrainingRunsListQueryParams,
    AutoresearchValidateCreateBody,
} from '@/generated/autoresearch/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const AutoresearchValidateCreateSchema = AutoresearchValidateCreateBody

const autoresearchValidateCreate = (): ToolBase<
    typeof AutoresearchValidateCreateSchema,
    Schemas.ValidatePipelineResponse
> => ({
    name: 'autoresearch-validate-create',
    schema: AutoresearchValidateCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AutoresearchValidateCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.target_event !== undefined) {
            body['target_event'] = params.target_event
        }
        if (params.horizon_days !== undefined) {
            body['horizon_days'] = params.horizon_days
        }
        if (params.prediction_mode !== undefined) {
            body['prediction_mode'] = params.prediction_mode
        }
        if (params.training_population !== undefined) {
            body['training_population'] = params.training_population
        }
        if (params.inference_population !== undefined) {
            body['inference_population'] = params.inference_population
        }
        const result = await context.api.request<Schemas.ValidatePipelineResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/validate/`,
            body,
        })
        return result
    },
})

const AutoresearchCreateSchema = AutoresearchCreateBody

const autoresearchCreate = (): ToolBase<
    typeof AutoresearchCreateSchema,
    WithPostHogUrl<Schemas.AutoresearchPipelineCreate>
> => ({
    name: 'autoresearch-create',
    schema: AutoresearchCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AutoresearchCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.target_event !== undefined) {
            body['target_event'] = params.target_event
        }
        if (params.target_definition !== undefined) {
            body['target_definition'] = params.target_definition
        }
        if (params.horizon_days !== undefined) {
            body['horizon_days'] = params.horizon_days
        }
        if (params.prediction_mode !== undefined) {
            body['prediction_mode'] = params.prediction_mode
        }
        if (params.training_population !== undefined) {
            body['training_population'] = params.training_population
        }
        if (params.inference_population !== undefined) {
            body['inference_population'] = params.inference_population
        }
        if (params.cadence_days !== undefined) {
            body['cadence_days'] = params.cadence_days
        }
        if (params.iteration_budget !== undefined) {
            body['iteration_budget'] = params.iteration_budget
        }
        if (params.success_auc !== undefined) {
            body['success_auc'] = params.success_auc
        }
        if (params.plateau_iterations !== undefined) {
            body['plateau_iterations'] = params.plateau_iterations
        }
        if (params.output_person_property !== undefined) {
            body['output_person_property'] = params.output_person_property
        }
        const result = await context.api.request<Schemas.AutoresearchPipelineCreate>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/`,
            body,
        })
        return await withPostHogUrl(context, result, `/autoresearch/${result.id}`)
    },
})

const AutoresearchListSchema = AutoresearchListQueryParams

const autoresearchList = (): ToolBase<
    typeof AutoresearchListSchema,
    WithPostHogUrl<Schemas.PaginatedAutoresearchPipelineList>
> => ({
    name: 'autoresearch-list',
    schema: AutoresearchListSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof AutoresearchListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAutoresearchPipelineList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'name',
                    'description',
                    'target_event',
                    'horizon_days',
                    'prediction_mode',
                    'status',
                    'iteration_budget',
                    'iteration_budget_remaining',
                    'last_scored_at',
                    'created_at',
                    'updated_at',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/autoresearch')
    },
})

const AutoresearchRetrieveSchema = AutoresearchRetrieveParams.omit({ project_id: true })

const autoresearchRetrieve = (): ToolBase<
    typeof AutoresearchRetrieveSchema,
    WithPostHogUrl<Schemas.AutoresearchPipeline>
> => ({
    name: 'autoresearch-retrieve',
    schema: AutoresearchRetrieveSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof AutoresearchRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoresearchPipeline>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/autoresearch/${result.id}`)
    },
})

const AutoresearchTrainCreateSchema = AutoresearchTrainCreateParams.omit({ project_id: true }).extend(
    AutoresearchTrainCreateBody.shape
)

const autoresearchTrainCreate = (): ToolBase<
    typeof AutoresearchTrainCreateSchema,
    Schemas.AutoresearchTrainingRun
> => ({
    name: 'autoresearch-train-create',
    schema: AutoresearchTrainCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AutoresearchTrainCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.iteration_budget !== undefined) {
            body['iteration_budget'] = params.iteration_budget
        }
        const result = await context.api.request<Schemas.AutoresearchTrainingRun>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.id))}/train/`,
            body,
        })
        return result
    },
})

const AutoresearchScoreCreateSchema = AutoresearchScoreCreateParams.omit({ project_id: true })

const autoresearchScoreCreate = (): ToolBase<typeof AutoresearchScoreCreateSchema, Schemas.AutoresearchRun> => ({
    name: 'autoresearch-score-create',
    schema: AutoresearchScoreCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AutoresearchScoreCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoresearchRun>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.id))}/score/`,
        })
        return result
    },
})

const AutoresearchPauseCreateSchema = AutoresearchPauseCreateParams.omit({ project_id: true }).extend(
    AutoresearchPauseCreateBody.shape
)

const autoresearchPauseCreate = (): ToolBase<typeof AutoresearchPauseCreateSchema, Schemas.AutoresearchPipeline> => ({
    name: 'autoresearch-pause-create',
    schema: AutoresearchPauseCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AutoresearchPauseCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.target_event !== undefined) {
            body['target_event'] = params.target_event
        }
        if (params.target_definition !== undefined) {
            body['target_definition'] = params.target_definition
        }
        if (params.horizon_days !== undefined) {
            body['horizon_days'] = params.horizon_days
        }
        if (params.prediction_mode !== undefined) {
            body['prediction_mode'] = params.prediction_mode
        }
        if (params.training_population !== undefined) {
            body['training_population'] = params.training_population
        }
        if (params.inference_population !== undefined) {
            body['inference_population'] = params.inference_population
        }
        if (params.cadence_days !== undefined) {
            body['cadence_days'] = params.cadence_days
        }
        if (params.iteration_budget !== undefined) {
            body['iteration_budget'] = params.iteration_budget
        }
        if (params.success_auc !== undefined) {
            body['success_auc'] = params.success_auc
        }
        if (params.plateau_iterations !== undefined) {
            body['plateau_iterations'] = params.plateau_iterations
        }
        if (params.output_person_property !== undefined) {
            body['output_person_property'] = params.output_person_property
        }
        const result = await context.api.request<Schemas.AutoresearchPipeline>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.id))}/pause/`,
            body,
        })
        return result
    },
})

const AutoresearchResumeCreateSchema = AutoresearchResumeCreateParams.omit({ project_id: true }).extend(
    AutoresearchResumeCreateBody.shape
)

const autoresearchResumeCreate = (): ToolBase<typeof AutoresearchResumeCreateSchema, Schemas.AutoresearchPipeline> => ({
    name: 'autoresearch-resume-create',
    schema: AutoresearchResumeCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AutoresearchResumeCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.target_event !== undefined) {
            body['target_event'] = params.target_event
        }
        if (params.target_definition !== undefined) {
            body['target_definition'] = params.target_definition
        }
        if (params.horizon_days !== undefined) {
            body['horizon_days'] = params.horizon_days
        }
        if (params.prediction_mode !== undefined) {
            body['prediction_mode'] = params.prediction_mode
        }
        if (params.training_population !== undefined) {
            body['training_population'] = params.training_population
        }
        if (params.inference_population !== undefined) {
            body['inference_population'] = params.inference_population
        }
        if (params.cadence_days !== undefined) {
            body['cadence_days'] = params.cadence_days
        }
        if (params.iteration_budget !== undefined) {
            body['iteration_budget'] = params.iteration_budget
        }
        if (params.success_auc !== undefined) {
            body['success_auc'] = params.success_auc
        }
        if (params.plateau_iterations !== undefined) {
            body['plateau_iterations'] = params.plateau_iterations
        }
        if (params.output_person_property !== undefined) {
            body['output_person_property'] = params.output_person_property
        }
        const result = await context.api.request<Schemas.AutoresearchPipeline>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.id))}/resume/`,
            body,
        })
        return result
    },
})

const AutoresearchArchiveCreateSchema = AutoresearchArchiveCreateParams.omit({ project_id: true }).extend(
    AutoresearchArchiveCreateBody.shape
)

const autoresearchArchiveCreate = (): ToolBase<
    typeof AutoresearchArchiveCreateSchema,
    Schemas.AutoresearchPipeline
> => ({
    name: 'autoresearch-archive-create',
    schema: AutoresearchArchiveCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AutoresearchArchiveCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.target_event !== undefined) {
            body['target_event'] = params.target_event
        }
        if (params.target_definition !== undefined) {
            body['target_definition'] = params.target_definition
        }
        if (params.horizon_days !== undefined) {
            body['horizon_days'] = params.horizon_days
        }
        if (params.prediction_mode !== undefined) {
            body['prediction_mode'] = params.prediction_mode
        }
        if (params.training_population !== undefined) {
            body['training_population'] = params.training_population
        }
        if (params.inference_population !== undefined) {
            body['inference_population'] = params.inference_population
        }
        if (params.cadence_days !== undefined) {
            body['cadence_days'] = params.cadence_days
        }
        if (params.iteration_budget !== undefined) {
            body['iteration_budget'] = params.iteration_budget
        }
        if (params.success_auc !== undefined) {
            body['success_auc'] = params.success_auc
        }
        if (params.plateau_iterations !== undefined) {
            body['plateau_iterations'] = params.plateau_iterations
        }
        if (params.output_person_property !== undefined) {
            body['output_person_property'] = params.output_person_property
        }
        const result = await context.api.request<Schemas.AutoresearchPipeline>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.id))}/archive/`,
            body,
        })
        return result
    },
})

const AutoresearchModelsListSchema = AutoresearchModelsListParams.omit({ project_id: true }).extend(
    AutoresearchModelsListQueryParams.shape
)

const autoresearchModelsList = (): ToolBase<
    typeof AutoresearchModelsListSchema,
    WithPostHogUrl<Schemas.PaginatedAutoresearchModelList>
> => ({
    name: 'autoresearch-models-list',
    schema: AutoresearchModelsListSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof AutoresearchModelsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAutoresearchModelList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.pipeline_id))}/models/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'pipeline',
                    'role',
                    'recipe_hash',
                    'holdout_score',
                    'realized_score',
                    'is_preliminary',
                    'agent_description',
                    'trained_on_start',
                    'trained_on_end',
                    'promoted_at',
                    'created_at',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/autoresearch')
    },
})

const AutoresearchModelsRetrieveSchema = AutoresearchModelsRetrieveParams.omit({ project_id: true })

const autoresearchModelsRetrieve = (): ToolBase<
    typeof AutoresearchModelsRetrieveSchema,
    Schemas.AutoresearchModel
> => ({
    name: 'autoresearch-models-retrieve',
    schema: AutoresearchModelsRetrieveSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof AutoresearchModelsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoresearchModel>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.pipeline_id))}/models/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const AutoresearchTrainingRunsListSchema = AutoresearchTrainingRunsListParams.omit({ project_id: true }).extend(
    AutoresearchTrainingRunsListQueryParams.shape
)

const autoresearchTrainingRunsList = (): ToolBase<
    typeof AutoresearchTrainingRunsListSchema,
    WithPostHogUrl<Schemas.PaginatedAutoresearchTrainingRunList>
> => ({
    name: 'autoresearch-training-runs-list',
    schema: AutoresearchTrainingRunsListSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof AutoresearchTrainingRunsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAutoresearchTrainingRunList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.pipeline_id))}/training_runs/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'pipeline',
                    'status',
                    'iteration_budget',
                    'iteration_count',
                    'best_holdout_score',
                    'error',
                    'started_at',
                    'completed_at',
                    'created_at',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/autoresearch')
    },
})

const AutoresearchRunsListSchema = AutoresearchRunsListParams.omit({ project_id: true }).extend(
    AutoresearchRunsListQueryParams.shape
)

const autoresearchRunsList = (): ToolBase<
    typeof AutoresearchRunsListSchema,
    WithPostHogUrl<Schemas.PaginatedAutoresearchRunList>
> => ({
    name: 'autoresearch-runs-list',
    schema: AutoresearchRunsListSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof AutoresearchRunsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAutoresearchRunList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.pipeline_id))}/runs/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'pipeline',
                    'model',
                    'run_type',
                    'status',
                    'rows_scored',
                    'error',
                    'started_at',
                    'completed_at',
                    'created_at',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/autoresearch')
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'autoresearch-validate-create': autoresearchValidateCreate,
    'autoresearch-create': autoresearchCreate,
    'autoresearch-list': autoresearchList,
    'autoresearch-retrieve': autoresearchRetrieve,
    'autoresearch-train-create': autoresearchTrainCreate,
    'autoresearch-score-create': autoresearchScoreCreate,
    'autoresearch-pause-create': autoresearchPauseCreate,
    'autoresearch-resume-create': autoresearchResumeCreate,
    'autoresearch-archive-create': autoresearchArchiveCreate,
    'autoresearch-models-list': autoresearchModelsList,
    'autoresearch-models-retrieve': autoresearchModelsRetrieve,
    'autoresearch-training-runs-list': autoresearchTrainingRunsList,
    'autoresearch-runs-list': autoresearchRunsList,
}
