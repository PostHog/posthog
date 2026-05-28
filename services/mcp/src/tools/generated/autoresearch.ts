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
    AutoresearchResolveTemplateCreateBody,
    AutoresearchResumeCreateBody,
    AutoresearchResumeCreateParams,
    AutoresearchRetrieveParams,
    AutoresearchRunsListParams,
    AutoresearchRunsListQueryParams,
    AutoresearchScoreCreateParams,
    AutoresearchSuggestionsCreateBody,
    AutoresearchSuggestionsCreateParams,
    AutoresearchSuggestionsListParams,
    AutoresearchSuggestionsListQueryParams,
    AutoresearchSuggestionsRetrieveParams,
    AutoresearchTemplatesListQueryParams,
    AutoresearchTrainCreateBody,
    AutoresearchTrainCreateParams,
    AutoresearchTrainingRunsCompleteCreateBody,
    AutoresearchTrainingRunsCompleteCreateParams,
    AutoresearchTrainingRunsCreateBody,
    AutoresearchTrainingRunsCreateParams,
    AutoresearchTrainingRunsIterationsCreateBody,
    AutoresearchTrainingRunsIterationsCreateParams,
    AutoresearchTrainingRunsListParams,
    AutoresearchTrainingRunsListQueryParams,
    AutoresearchValidateCreateBody,
    AutoresearchValidateOnlineCreateBody,
    AutoresearchValidateOnlineCreateParams,
} from '@/generated/autoresearch/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

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

const AutoresearchResolveTemplateCreateSchema = AutoresearchResolveTemplateCreateBody

const autoresearchResolveTemplateCreate = (): ToolBase<
    typeof AutoresearchResolveTemplateCreateSchema,
    Schemas.ResolvedTemplate
> => ({
    name: 'autoresearch-resolve-template-create',
    schema: AutoresearchResolveTemplateCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AutoresearchResolveTemplateCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.template_key !== undefined) {
            body['template_key'] = params.template_key
        }
        if (params.target_event !== undefined) {
            body['target_event'] = params.target_event
        }
        if (params.horizon_days !== undefined) {
            body['horizon_days'] = params.horizon_days
        }
        const result = await context.api.request<Schemas.ResolvedTemplate>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/resolve-template/`,
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

const AutoresearchSuggestionsCreateSchema = AutoresearchSuggestionsCreateParams.omit({ project_id: true }).extend(
    AutoresearchSuggestionsCreateBody.shape
)

const autoresearchSuggestionsCreate = (): ToolBase<
    typeof AutoresearchSuggestionsCreateSchema,
    Schemas.AutoresearchSuggestion
> => ({
    name: 'autoresearch-suggestions-create',
    schema: AutoresearchSuggestionsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AutoresearchSuggestionsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.prompt !== undefined) {
            body['prompt'] = params.prompt
        }
        if (params.priority !== undefined) {
            body['priority'] = params.priority
        }
        const result = await context.api.request<Schemas.AutoresearchSuggestion>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.pipeline_id))}/suggestions/`,
            body,
        })
        return result
    },
})

const AutoresearchSuggestionsListSchema = AutoresearchSuggestionsListParams.omit({ project_id: true }).extend(
    AutoresearchSuggestionsListQueryParams.shape
)

const autoresearchSuggestionsList = (): ToolBase<
    typeof AutoresearchSuggestionsListSchema,
    WithPostHogUrl<Schemas.PaginatedAutoresearchSuggestionList>
> => ({
    name: 'autoresearch-suggestions-list',
    schema: AutoresearchSuggestionsListSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof AutoresearchSuggestionsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAutoresearchSuggestionList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.pipeline_id))}/suggestions/`,
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
                    'prompt',
                    'priority',
                    'status',
                    'source',
                    'agent_response',
                    'linked_iteration_ids',
                    'created_at',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/autoresearch')
    },
})

const AutoresearchSuggestionsRetrieveSchema = AutoresearchSuggestionsRetrieveParams.omit({ project_id: true })

const autoresearchSuggestionsRetrieve = (): ToolBase<
    typeof AutoresearchSuggestionsRetrieveSchema,
    Schemas.AutoresearchSuggestion
> => ({
    name: 'autoresearch-suggestions-retrieve',
    schema: AutoresearchSuggestionsRetrieveSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof AutoresearchSuggestionsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoresearchSuggestion>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.pipeline_id))}/suggestions/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const AutoresearchTemplatesListSchema = AutoresearchTemplatesListQueryParams

const autoresearchTemplatesList = (): ToolBase<
    typeof AutoresearchTemplatesListSchema,
    WithPostHogUrl<Schemas.PaginatedTemplateInfoList>
> => ({
    name: 'autoresearch-templates-list',
    schema: AutoresearchTemplatesListSchema,
    handler: async (context: Context, params: z.infer<typeof AutoresearchTemplatesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedTemplateInfoList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/templates/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'key',
                    'display_name',
                    'description',
                    'prediction_mode',
                    'default_horizon_days',
                    'requires_user_event',
                    'requires_activity_resolution',
                    'notes',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/autoresearch')
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

const AutoresearchTrainingRunsCompleteCreateSchema = AutoresearchTrainingRunsCompleteCreateParams.omit({
    project_id: true,
}).extend(AutoresearchTrainingRunsCompleteCreateBody.shape)

const autoresearchTrainingRunsCompleteCreate = (): ToolBase<
    typeof AutoresearchTrainingRunsCompleteCreateSchema,
    Schemas.AutoresearchTrainingRun
> => ({
    name: 'autoresearch-training-runs-complete-create',
    schema: AutoresearchTrainingRunsCompleteCreateSchema,
    mcpVersion: 2,
    handler: async (context: Context, params: z.infer<typeof AutoresearchTrainingRunsCompleteCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.best_iteration_id !== undefined) {
            body['best_iteration_id'] = params.best_iteration_id
        }
        if (params.model_explanation !== undefined) {
            body['model_explanation'] = params.model_explanation
        }
        const result = await context.api.request<Schemas.AutoresearchTrainingRun>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.pipeline_id))}/training_runs/${encodeURIComponent(String(params.id))}/complete/`,
            body,
        })
        return result
    },
})

const AutoresearchTrainingRunsCreateSchema = AutoresearchTrainingRunsCreateParams.omit({ project_id: true }).extend(
    AutoresearchTrainingRunsCreateBody.shape
)

const autoresearchTrainingRunsCreate = (): ToolBase<
    typeof AutoresearchTrainingRunsCreateSchema,
    Schemas.AutoresearchTrainingRun
> => ({
    name: 'autoresearch-training-runs-create',
    schema: AutoresearchTrainingRunsCreateSchema,
    mcpVersion: 2,
    handler: async (context: Context, params: z.infer<typeof AutoresearchTrainingRunsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.iteration_budget !== undefined) {
            body['iteration_budget'] = params.iteration_budget
        }
        const result = await context.api.request<Schemas.AutoresearchTrainingRun>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.pipeline_id))}/training_runs/`,
            body,
        })
        return result
    },
})

const AutoresearchTrainingRunsIterationsCreateSchema = AutoresearchTrainingRunsIterationsCreateParams.omit({
    project_id: true,
}).extend(AutoresearchTrainingRunsIterationsCreateBody.shape)

const autoresearchTrainingRunsIterationsCreate = (): ToolBase<
    typeof AutoresearchTrainingRunsIterationsCreateSchema,
    Schemas.AutoresearchIteration
> => ({
    name: 'autoresearch-training-runs-iterations-create',
    schema: AutoresearchTrainingRunsIterationsCreateSchema,
    mcpVersion: 2,
    handler: async (context: Context, params: z.infer<typeof AutoresearchTrainingRunsIterationsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.iteration_number !== undefined) {
            body['iteration_number'] = params.iteration_number
        }
        if (params.recipe_snapshot !== undefined) {
            body['recipe_snapshot'] = params.recipe_snapshot
        }
        if (params.model_spec !== undefined) {
            body['model_spec'] = params.model_spec
        }
        if (params.status !== undefined) {
            body['status'] = params.status
        }
        if (params.train_score !== undefined) {
            body['train_score'] = params.train_score
        }
        if (params.holdout_score !== undefined) {
            body['holdout_score'] = params.holdout_score
        }
        if (params.agent_description !== undefined) {
            body['agent_description'] = params.agent_description
        }
        if (params.agent_confidence !== undefined) {
            body['agent_confidence'] = params.agent_confidence
        }
        const result = await context.api.request<Schemas.AutoresearchIteration>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.pipeline_id))}/training_runs/${encodeURIComponent(String(params.id))}/iterations/`,
            body,
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

const AutoresearchValidateOnlineCreateSchema = AutoresearchValidateOnlineCreateParams.omit({ project_id: true }).extend(
    AutoresearchValidateOnlineCreateBody.shape
)

const autoresearchValidateOnlineCreate = (): ToolBase<
    typeof AutoresearchValidateOnlineCreateSchema,
    Schemas.PaginatedAutoresearchRunList
> => ({
    name: 'autoresearch-validate-online-create',
    schema: AutoresearchValidateOnlineCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AutoresearchValidateOnlineCreateSchema>) => {
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
        const result = await context.api.request<Schemas.PaginatedAutoresearchRunList>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.id))}/validate-online/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'autoresearch-archive-create': autoresearchArchiveCreate,
    'autoresearch-create': autoresearchCreate,
    'autoresearch-list': autoresearchList,
    'autoresearch-models-list': autoresearchModelsList,
    'autoresearch-models-retrieve': autoresearchModelsRetrieve,
    'autoresearch-pause-create': autoresearchPauseCreate,
    'autoresearch-resolve-template-create': autoresearchResolveTemplateCreate,
    'autoresearch-resume-create': autoresearchResumeCreate,
    'autoresearch-retrieve': autoresearchRetrieve,
    'autoresearch-runs-list': autoresearchRunsList,
    'autoresearch-score-create': autoresearchScoreCreate,
    'autoresearch-suggestions-create': autoresearchSuggestionsCreate,
    'autoresearch-suggestions-list': autoresearchSuggestionsList,
    'autoresearch-suggestions-retrieve': autoresearchSuggestionsRetrieve,
    'autoresearch-templates-list': autoresearchTemplatesList,
    'autoresearch-train-create': autoresearchTrainCreate,
    'autoresearch-training-runs-complete-create': autoresearchTrainingRunsCompleteCreate,
    'autoresearch-training-runs-create': autoresearchTrainingRunsCreate,
    'autoresearch-training-runs-iterations-create': autoresearchTrainingRunsIterationsCreate,
    'autoresearch-training-runs-list': autoresearchTrainingRunsList,
    'autoresearch-validate-create': autoresearchValidateCreate,
    'autoresearch-validate-online-create': autoresearchValidateOnlineCreate,
}
