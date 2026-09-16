// AUTO-GENERATED from products/autoresearch/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/autoresearch/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const AutoresearchArchiveCreateSchema = () => {
    const AutoresearchArchiveCreateParams = orvalSchemas.AutoresearchArchiveCreateParams()
    return AutoresearchArchiveCreateParams.omit({ project_id: true })
}

const autoresearchArchiveCreate = (): ToolBase<
    ReturnType<typeof AutoresearchArchiveCreateSchema>,
    Schemas.AutoresearchPipeline
> => ({
    name: 'autoresearch-archive-create',
    schema: AutoresearchArchiveCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AutoresearchArchiveCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoresearchPipeline>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.id))}/archive/`,
        })
        return result
    },
})

const AutoresearchCreateSchema = () => {
    const AutoresearchCreateBody = orvalSchemas.AutoresearchCreateBody()
    return AutoresearchCreateBody
}

const autoresearchCreate = (): ToolBase<ReturnType<typeof AutoresearchCreateSchema>, Schemas.AutoresearchPipeline> => ({
    name: 'autoresearch-create',
    schema: AutoresearchCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AutoresearchCreateSchema>>) => {
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
        if (params.training_lookback_days !== undefined) {
            body['training_lookback_days'] = params.training_lookback_days
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/`,
            body,
        })
        return result
    },
})

const AutoresearchListSchema = () => {
    const AutoresearchListQueryParams = orvalSchemas.AutoresearchListQueryParams()
    return AutoresearchListQueryParams
}

const autoresearchList = (): ToolBase<
    ReturnType<typeof AutoresearchListSchema>,
    WithPostHogUrl<Schemas.PaginatedAutoresearchPipelineList>
> => ({
    name: 'autoresearch-list',
    schema: AutoresearchListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AutoresearchListSchema>>) => {
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
                    'status',
                    'iteration_budget',
                    'iteration_budget_remaining',
                    'last_scored_at',
                    'created_at',
                    'updated_at',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/')
    },
})

const AutoresearchMaterializeFeaturesSchema = () => {
    const AutoresearchTrainingRunsMaterializeFeaturesCreateBody =
        orvalSchemas.AutoresearchTrainingRunsMaterializeFeaturesCreateBody()
    const AutoresearchTrainingRunsMaterializeFeaturesCreateParams =
        orvalSchemas.AutoresearchTrainingRunsMaterializeFeaturesCreateParams()
    return AutoresearchTrainingRunsMaterializeFeaturesCreateParams.omit({ project_id: true }).extend(
        AutoresearchTrainingRunsMaterializeFeaturesCreateBody.shape
    )
}

const autoresearchMaterializeFeatures = (): ToolBase<
    ReturnType<typeof AutoresearchMaterializeFeaturesSchema>,
    Schemas.MaterializeFeaturesResponse
> => ({
    name: 'autoresearch-materialize-features',
    schema: AutoresearchMaterializeFeaturesSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AutoresearchMaterializeFeaturesSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.features_sql !== undefined) {
            body['features_sql'] = params.features_sql
        }
        const result = await context.api.request<Schemas.MaterializeFeaturesResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.pipeline_id))}/training_runs/${encodeURIComponent(String(params.id))}/materialize-features/`,
            body,
        })
        return result
    },
})

const AutoresearchModelsListSchema = () => {
    const AutoresearchModelsListParams = orvalSchemas.AutoresearchModelsListParams()
    const AutoresearchModelsListQueryParams = orvalSchemas.AutoresearchModelsListQueryParams()
    return AutoresearchModelsListParams.omit({ project_id: true }).extend(AutoresearchModelsListQueryParams.shape)
}

const autoresearchModelsList = (): ToolBase<
    ReturnType<typeof AutoresearchModelsListSchema>,
    WithPostHogUrl<Schemas.PaginatedAutoresearchModelList>
> => ({
    name: 'autoresearch-models-list',
    schema: AutoresearchModelsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AutoresearchModelsListSchema>>) => {
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
        return await withPostHogUrl(context, filtered, '/')
    },
})

const AutoresearchModelsRetrieveSchema = () => {
    const AutoresearchModelsRetrieveParams = orvalSchemas.AutoresearchModelsRetrieveParams()
    return AutoresearchModelsRetrieveParams.omit({ project_id: true })
}

const autoresearchModelsRetrieve = (): ToolBase<
    ReturnType<typeof AutoresearchModelsRetrieveSchema>,
    Schemas.AutoresearchModel
> => ({
    name: 'autoresearch-models-retrieve',
    schema: AutoresearchModelsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AutoresearchModelsRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoresearchModel>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.pipeline_id))}/models/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const AutoresearchPauseCreateSchema = () => {
    const AutoresearchPauseCreateParams = orvalSchemas.AutoresearchPauseCreateParams()
    return AutoresearchPauseCreateParams.omit({ project_id: true })
}

const autoresearchPauseCreate = (): ToolBase<
    ReturnType<typeof AutoresearchPauseCreateSchema>,
    Schemas.AutoresearchPipeline
> => ({
    name: 'autoresearch-pause-create',
    schema: AutoresearchPauseCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AutoresearchPauseCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoresearchPipeline>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.id))}/pause/`,
        })
        return result
    },
})

const AutoresearchResumeCreateSchema = () => {
    const AutoresearchResumeCreateParams = orvalSchemas.AutoresearchResumeCreateParams()
    return AutoresearchResumeCreateParams.omit({ project_id: true })
}

const autoresearchResumeCreate = (): ToolBase<
    ReturnType<typeof AutoresearchResumeCreateSchema>,
    Schemas.AutoresearchPipeline
> => ({
    name: 'autoresearch-resume-create',
    schema: AutoresearchResumeCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AutoresearchResumeCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoresearchPipeline>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.id))}/resume/`,
        })
        return result
    },
})

const AutoresearchRetrieveSchema = () => {
    const AutoresearchRetrieveParams = orvalSchemas.AutoresearchRetrieveParams()
    return AutoresearchRetrieveParams.omit({ project_id: true })
}

const autoresearchRetrieve = (): ToolBase<
    ReturnType<typeof AutoresearchRetrieveSchema>,
    Schemas.AutoresearchPipeline
> => ({
    name: 'autoresearch-retrieve',
    schema: AutoresearchRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AutoresearchRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoresearchPipeline>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const AutoresearchRunsListSchema = () => {
    const AutoresearchRunsListParams = orvalSchemas.AutoresearchRunsListParams()
    const AutoresearchRunsListQueryParams = orvalSchemas.AutoresearchRunsListQueryParams()
    return AutoresearchRunsListParams.omit({ project_id: true }).extend(AutoresearchRunsListQueryParams.shape)
}

const autoresearchRunsList = (): ToolBase<
    ReturnType<typeof AutoresearchRunsListSchema>,
    WithPostHogUrl<Schemas.PaginatedAutoresearchRunList>
> => ({
    name: 'autoresearch-runs-list',
    schema: AutoresearchRunsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AutoresearchRunsListSchema>>) => {
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
        return await withPostHogUrl(context, filtered, '/')
    },
})

const AutoresearchScoreCreateSchema = () => {
    const AutoresearchScoreCreateParams = orvalSchemas.AutoresearchScoreCreateParams()
    return AutoresearchScoreCreateParams.omit({ project_id: true })
}

const autoresearchScoreCreate = (): ToolBase<
    ReturnType<typeof AutoresearchScoreCreateSchema>,
    Schemas.AutoresearchRun
> => ({
    name: 'autoresearch-score-create',
    schema: AutoresearchScoreCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AutoresearchScoreCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoresearchRun>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.id))}/score/`,
        })
        return result
    },
})

const AutoresearchSuggestionsCreateSchema = () => {
    const AutoresearchSuggestionsCreateBody = orvalSchemas.AutoresearchSuggestionsCreateBody()
    const AutoresearchSuggestionsCreateParams = orvalSchemas.AutoresearchSuggestionsCreateParams()
    return AutoresearchSuggestionsCreateParams.omit({ project_id: true }).extend(
        AutoresearchSuggestionsCreateBody.shape
    )
}

const autoresearchSuggestionsCreate = (): ToolBase<
    ReturnType<typeof AutoresearchSuggestionsCreateSchema>,
    Schemas.AutoresearchSuggestion
> => ({
    name: 'autoresearch-suggestions-create',
    schema: AutoresearchSuggestionsCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AutoresearchSuggestionsCreateSchema>>) => {
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

const AutoresearchSuggestionsListSchema = () => {
    const AutoresearchSuggestionsListParams = orvalSchemas.AutoresearchSuggestionsListParams()
    const AutoresearchSuggestionsListQueryParams = orvalSchemas.AutoresearchSuggestionsListQueryParams()
    return AutoresearchSuggestionsListParams.omit({ project_id: true }).extend(
        AutoresearchSuggestionsListQueryParams.shape
    )
}

const autoresearchSuggestionsList = (): ToolBase<
    ReturnType<typeof AutoresearchSuggestionsListSchema>,
    WithPostHogUrl<Schemas.PaginatedAutoresearchSuggestionList>
> => ({
    name: 'autoresearch-suggestions-list',
    schema: AutoresearchSuggestionsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AutoresearchSuggestionsListSchema>>) => {
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
        return await withPostHogUrl(context, filtered, '/')
    },
})

const AutoresearchSuggestionsRespondSchema = () => {
    const AutoresearchSuggestionsRespondCreateBody = orvalSchemas.AutoresearchSuggestionsRespondCreateBody()
    const AutoresearchSuggestionsRespondCreateParams = orvalSchemas.AutoresearchSuggestionsRespondCreateParams()
    return AutoresearchSuggestionsRespondCreateParams.omit({ project_id: true }).extend(
        AutoresearchSuggestionsRespondCreateBody.shape
    )
}

const autoresearchSuggestionsRespond = (): ToolBase<
    ReturnType<typeof AutoresearchSuggestionsRespondSchema>,
    Schemas.AutoresearchSuggestion
> => ({
    name: 'autoresearch-suggestions-respond',
    schema: AutoresearchSuggestionsRespondSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AutoresearchSuggestionsRespondSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.status !== undefined) {
            body['status'] = params.status
        }
        if (params.agent_response !== undefined) {
            body['agent_response'] = params.agent_response
        }
        const result = await context.api.request<Schemas.AutoresearchSuggestion>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.pipeline_id))}/suggestions/${encodeURIComponent(String(params.id))}/respond/`,
            body,
        })
        return result
    },
})

const AutoresearchTemplatesListSchema = () => z.object({})

const autoresearchTemplatesList = (): ToolBase<
    ReturnType<typeof AutoresearchTemplatesListSchema>,
    Schemas.TemplateInfo[]
> => ({
    name: 'autoresearch-templates-list',
    schema: AutoresearchTemplatesListSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof AutoresearchTemplatesListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TemplateInfo[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/templates/`,
        })
        return result
    },
})

const AutoresearchTrainCreateSchema = () => {
    const AutoresearchTrainCreateBody = orvalSchemas.AutoresearchTrainCreateBody()
    const AutoresearchTrainCreateParams = orvalSchemas.AutoresearchTrainCreateParams()
    return AutoresearchTrainCreateParams.omit({ project_id: true }).extend(AutoresearchTrainCreateBody.shape)
}

const autoresearchTrainCreate = (): ToolBase<
    ReturnType<typeof AutoresearchTrainCreateSchema>,
    Schemas.AutoresearchTrainingRun
> => ({
    name: 'autoresearch-train-create',
    schema: AutoresearchTrainCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AutoresearchTrainCreateSchema>>) => {
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

const AutoresearchTrainingRunsArtifactsGetCreateSchema = () => {
    const AutoresearchTrainingRunsArtifactsGetCreateBody = orvalSchemas.AutoresearchTrainingRunsArtifactsGetCreateBody()
    const AutoresearchTrainingRunsArtifactsGetCreateParams =
        orvalSchemas.AutoresearchTrainingRunsArtifactsGetCreateParams()
    return AutoresearchTrainingRunsArtifactsGetCreateParams.omit({ project_id: true }).extend(
        AutoresearchTrainingRunsArtifactsGetCreateBody.shape
    )
}

const autoresearchTrainingRunsArtifactsGetCreate = (): ToolBase<
    ReturnType<typeof AutoresearchTrainingRunsArtifactsGetCreateSchema>,
    Schemas.ArtifactContent
> => ({
    name: 'autoresearch-training-runs-artifacts-get-create',
    schema: AutoresearchTrainingRunsArtifactsGetCreateSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof AutoresearchTrainingRunsArtifactsGetCreateSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.path !== undefined) {
            body['path'] = params.path
        }
        const result = await context.api.request<Schemas.ArtifactContent>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.pipeline_id))}/training_runs/${encodeURIComponent(String(params.id))}/artifacts/get/`,
            body,
        })
        return result
    },
})

const AutoresearchTrainingRunsArtifactsRetrieveSchema = () => {
    const AutoresearchTrainingRunsArtifactsRetrieveParams =
        orvalSchemas.AutoresearchTrainingRunsArtifactsRetrieveParams()
    return AutoresearchTrainingRunsArtifactsRetrieveParams.omit({ project_id: true })
}

const autoresearchTrainingRunsArtifactsRetrieve = (): ToolBase<
    ReturnType<typeof AutoresearchTrainingRunsArtifactsRetrieveSchema>,
    Schemas.ArtifactList
> => ({
    name: 'autoresearch-training-runs-artifacts-retrieve',
    schema: AutoresearchTrainingRunsArtifactsRetrieveSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof AutoresearchTrainingRunsArtifactsRetrieveSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ArtifactList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.pipeline_id))}/training_runs/${encodeURIComponent(String(params.id))}/artifacts/`,
        })
        return result
    },
})

const AutoresearchTrainingRunsArtifactsUploadCreateSchema = () => {
    const AutoresearchTrainingRunsArtifactsUploadCreateBody =
        orvalSchemas.AutoresearchTrainingRunsArtifactsUploadCreateBody()
    const AutoresearchTrainingRunsArtifactsUploadCreateParams =
        orvalSchemas.AutoresearchTrainingRunsArtifactsUploadCreateParams()
    return AutoresearchTrainingRunsArtifactsUploadCreateParams.omit({ project_id: true }).extend(
        AutoresearchTrainingRunsArtifactsUploadCreateBody.shape
    )
}

const autoresearchTrainingRunsArtifactsUploadCreate = (): ToolBase<
    ReturnType<typeof AutoresearchTrainingRunsArtifactsUploadCreateSchema>,
    Schemas.StoredArtifact
> => ({
    name: 'autoresearch-training-runs-artifacts-upload-create',
    schema: AutoresearchTrainingRunsArtifactsUploadCreateSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof AutoresearchTrainingRunsArtifactsUploadCreateSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.path !== undefined) {
            body['path'] = params.path
        }
        if (params.content_base64 !== undefined) {
            body['content_base64'] = params.content_base64
        }
        const result = await context.api.request<Schemas.StoredArtifact>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.pipeline_id))}/training_runs/${encodeURIComponent(String(params.id))}/artifacts/upload/`,
            body,
        })
        return result
    },
})

const AutoresearchTrainingRunsCompleteCreateSchema = () => {
    const AutoresearchTrainingRunsCompleteCreateBody = orvalSchemas.AutoresearchTrainingRunsCompleteCreateBody()
    const AutoresearchTrainingRunsCompleteCreateParams = orvalSchemas.AutoresearchTrainingRunsCompleteCreateParams()
    return AutoresearchTrainingRunsCompleteCreateParams.omit({ project_id: true }).extend(
        AutoresearchTrainingRunsCompleteCreateBody.shape
    )
}

const autoresearchTrainingRunsCompleteCreate = (): ToolBase<
    ReturnType<typeof AutoresearchTrainingRunsCompleteCreateSchema>,
    Schemas.AutoresearchTrainingRun
> => ({
    name: 'autoresearch-training-runs-complete-create',
    schema: AutoresearchTrainingRunsCompleteCreateSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof AutoresearchTrainingRunsCompleteCreateSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.best_iteration_id !== undefined) {
            body['best_iteration_id'] = params.best_iteration_id
        }
        if (params.model_explanation !== undefined) {
            body['model_explanation'] = params.model_explanation
        }
        if (params.recommended_next !== undefined) {
            body['recommended_next'] = params.recommended_next
        }
        if (params.distillation !== undefined) {
            body['distillation'] = params.distillation
        }
        const result = await context.api.request<Schemas.AutoresearchTrainingRun>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.pipeline_id))}/training_runs/${encodeURIComponent(String(params.id))}/complete/`,
            body,
        })
        return result
    },
})

const AutoresearchTrainingRunsCreateSchema = () => {
    const AutoresearchTrainingRunsCreateBody = orvalSchemas.AutoresearchTrainingRunsCreateBody()
    const AutoresearchTrainingRunsCreateParams = orvalSchemas.AutoresearchTrainingRunsCreateParams()
    return AutoresearchTrainingRunsCreateParams.omit({ project_id: true }).extend(
        AutoresearchTrainingRunsCreateBody.shape
    )
}

const autoresearchTrainingRunsCreate = (): ToolBase<
    ReturnType<typeof AutoresearchTrainingRunsCreateSchema>,
    Schemas.AutoresearchTrainingRun
> => ({
    name: 'autoresearch-training-runs-create',
    schema: AutoresearchTrainingRunsCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AutoresearchTrainingRunsCreateSchema>>) => {
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

const AutoresearchTrainingRunsHistorySchema = () => {
    const AutoresearchTrainingRunsHistoryRetrieveParams = orvalSchemas.AutoresearchTrainingRunsHistoryRetrieveParams()
    const AutoresearchTrainingRunsHistoryRetrieveQueryParams =
        orvalSchemas.AutoresearchTrainingRunsHistoryRetrieveQueryParams()
    return AutoresearchTrainingRunsHistoryRetrieveParams.omit({ project_id: true }).extend(
        AutoresearchTrainingRunsHistoryRetrieveQueryParams.shape
    )
}

const autoresearchTrainingRunsHistory = (): ToolBase<
    ReturnType<typeof AutoresearchTrainingRunsHistorySchema>,
    Schemas.TrainingRunHistory
> => ({
    name: 'autoresearch-training-runs-history',
    schema: AutoresearchTrainingRunsHistorySchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AutoresearchTrainingRunsHistorySchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TrainingRunHistory>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.pipeline_id))}/training_runs/history/`,
            query: {
                limit: params.limit,
            },
        })
        return result
    },
})

const AutoresearchTrainingRunsIterationsCreateSchema = () => {
    const AutoresearchTrainingRunsIterationsCreateBody = orvalSchemas.AutoresearchTrainingRunsIterationsCreateBody()
    const AutoresearchTrainingRunsIterationsCreateParams = orvalSchemas.AutoresearchTrainingRunsIterationsCreateParams()
    return AutoresearchTrainingRunsIterationsCreateParams.omit({ project_id: true }).extend(
        AutoresearchTrainingRunsIterationsCreateBody.shape
    )
}

const autoresearchTrainingRunsIterationsCreate = (): ToolBase<
    ReturnType<typeof AutoresearchTrainingRunsIterationsCreateSchema>,
    Schemas.AutoresearchIteration
> => ({
    name: 'autoresearch-training-runs-iterations-create',
    schema: AutoresearchTrainingRunsIterationsCreateSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof AutoresearchTrainingRunsIterationsCreateSchema>>
    ) => {
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
        if (params.parent_suggestion !== undefined) {
            body['parent_suggestion'] = params.parent_suggestion
        }
        const result = await context.api.request<Schemas.AutoresearchIteration>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/autoresearch/${encodeURIComponent(String(params.pipeline_id))}/training_runs/${encodeURIComponent(String(params.id))}/iterations/`,
            body,
        })
        return result
    },
})

const AutoresearchTrainingRunsListSchema = () => {
    const AutoresearchTrainingRunsListParams = orvalSchemas.AutoresearchTrainingRunsListParams()
    const AutoresearchTrainingRunsListQueryParams = orvalSchemas.AutoresearchTrainingRunsListQueryParams()
    return AutoresearchTrainingRunsListParams.omit({ project_id: true }).extend(
        AutoresearchTrainingRunsListQueryParams.shape
    )
}

const autoresearchTrainingRunsList = (): ToolBase<
    ReturnType<typeof AutoresearchTrainingRunsListSchema>,
    WithPostHogUrl<Schemas.PaginatedAutoresearchTrainingRunList>
> => ({
    name: 'autoresearch-training-runs-list',
    schema: AutoresearchTrainingRunsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AutoresearchTrainingRunsListSchema>>) => {
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
        return await withPostHogUrl(context, filtered, '/')
    },
})

const AutoresearchValidateCreateSchema = () => {
    const AutoresearchValidateCreateBody = orvalSchemas.AutoresearchValidateCreateBody()
    return AutoresearchValidateCreateBody
}

const autoresearchValidateCreate = (): ToolBase<
    ReturnType<typeof AutoresearchValidateCreateSchema>,
    Schemas.ValidatePipelineResponse
> => ({
    name: 'autoresearch-validate-create',
    schema: AutoresearchValidateCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AutoresearchValidateCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.target_event !== undefined) {
            body['target_event'] = params.target_event
        }
        if (params.target_definition !== undefined) {
            body['target_definition'] = params.target_definition
        }
        if (params.horizon_days !== undefined) {
            body['horizon_days'] = params.horizon_days
        }
        if (params.training_lookback_days !== undefined) {
            body['training_lookback_days'] = params.training_lookback_days
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

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'autoresearch-archive-create': autoresearchArchiveCreate,
    'autoresearch-create': autoresearchCreate,
    'autoresearch-list': autoresearchList,
    'autoresearch-materialize-features': autoresearchMaterializeFeatures,
    'autoresearch-models-list': autoresearchModelsList,
    'autoresearch-models-retrieve': autoresearchModelsRetrieve,
    'autoresearch-pause-create': autoresearchPauseCreate,
    'autoresearch-resume-create': autoresearchResumeCreate,
    'autoresearch-retrieve': autoresearchRetrieve,
    'autoresearch-runs-list': autoresearchRunsList,
    'autoresearch-score-create': autoresearchScoreCreate,
    'autoresearch-suggestions-create': autoresearchSuggestionsCreate,
    'autoresearch-suggestions-list': autoresearchSuggestionsList,
    'autoresearch-suggestions-respond': autoresearchSuggestionsRespond,
    'autoresearch-templates-list': autoresearchTemplatesList,
    'autoresearch-train-create': autoresearchTrainCreate,
    'autoresearch-training-runs-artifacts-get-create': autoresearchTrainingRunsArtifactsGetCreate,
    'autoresearch-training-runs-artifacts-retrieve': autoresearchTrainingRunsArtifactsRetrieve,
    'autoresearch-training-runs-artifacts-upload-create': autoresearchTrainingRunsArtifactsUploadCreate,
    'autoresearch-training-runs-complete-create': autoresearchTrainingRunsCompleteCreate,
    'autoresearch-training-runs-create': autoresearchTrainingRunsCreate,
    'autoresearch-training-runs-history': autoresearchTrainingRunsHistory,
    'autoresearch-training-runs-iterations-create': autoresearchTrainingRunsIterationsCreate,
    'autoresearch-training-runs-list': autoresearchTrainingRunsList,
    'autoresearch-validate-create': autoresearchValidateCreate,
}
