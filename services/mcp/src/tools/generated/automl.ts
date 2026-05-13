// AUTO-GENERATED from products/automl/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    AutomlPipelinesArchiveCreateParams,
    AutomlPipelinesCreateBody,
    AutomlPipelinesListQueryParams,
    AutomlPipelinesPartialUpdateBody,
    AutomlPipelinesPartialUpdateParams,
    AutomlPipelinesPauseCreateParams,
    AutomlPipelinesResumeCreateParams,
    AutomlPipelinesRetrieveParams,
    AutomlPipelinesStartCreateParams,
    AutomlPipelinesValidateCreateBody,
} from '@/generated/automl/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const AutomlListSchema = AutomlPipelinesListQueryParams

const automlList = (): ToolBase<typeof AutomlListSchema, WithPostHogUrl<Schemas.PaginatedAutoMLPipelineDTOList>> => ({
    name: 'automl-list',
    schema: AutomlListSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAutoMLPipelineDTOList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(
            context,
            {
                ...result,
                results: await Promise.all(
                    (result.results ?? []).map((item) => withPostHogUrl(context, item, `/automl/${item.id}`))
                ),
            },
            '/automl'
        )
    },
})

const AutomlGetSchema = AutomlPipelinesRetrieveParams.omit({ project_id: true })

const automlGet = (): ToolBase<typeof AutomlGetSchema, WithPostHogUrl<Schemas.AutoMLPipelineDTO>> => ({
    name: 'automl-get',
    schema: AutomlGetSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoMLPipelineDTO>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/automl/${result.id}`)
    },
})

const AutomlCreateSchema = AutomlPipelinesCreateBody.extend({
    name: AutomlPipelinesCreateBody.shape['name'].describe(
        'Human-readable label for the pipeline. Shows up in the UI and in property names. Keep it short and unique within the team.'
    ),
    task_type: AutomlPipelinesCreateBody.shape['task_type'].describe(
        'One of "clustering", "classification", "regression", or "forecasting". Determines what kind of model is trained and how predictions are surfaced.'
    ),
    config: AutomlPipelinesCreateBody.shape['config'].describe(
        'Task-type-specific configuration (target event, horizon, cluster count, forecasting window, etc.). Shape depends on task_type. See the AutoML design doc for per-task fields.'
    ),
    training_population: AutomlPipelinesCreateBody.shape['training_population'].describe(
        'Population definition (HogQL or filter spec) describing which persons, groups, or events are eligible to be drawn into the training set.'
    ),
    inference_population: AutomlPipelinesCreateBody.shape['inference_population'].describe(
        'Population definition describing who the model is scored against on each scheduled run. Usually broader than training_population.'
    ),
    inference_cadence: AutomlPipelinesCreateBody.shape['inference_cadence'].describe(
        'How often inference runs after the pipeline is active. One of "hourly", "daily", "weekly", "monthly", or "never" (manual only).'
    ),
    retraining_cadence: AutomlPipelinesCreateBody.shape['retraining_cadence'].describe(
        'How often the model is refit on a rolling window. One of "hourly", "daily", "weekly", "monthly", or "never".'
    ),
    autonomy: AutomlPipelinesCreateBody.shape['autonomy'].describe(
        'Output gate. "shadow_only" surfaces predictions internally but never writes person/group properties or emits events. "champion_only" writes from the active champion model. "promote_eligible" lets challenger models graduate to champion automatically when metrics pass thresholds.'
    ),
    output_property_name: AutomlPipelinesCreateBody.shape['output_property_name'].describe(
        'Name of the person or group property where predictions are written. Optional; if blank the pipeline emits events only.'
    ),
})

const automlCreate = (): ToolBase<typeof AutomlCreateSchema, Schemas.AutoMLPipelineDTO> => ({
    name: 'automl-create',
    schema: AutomlCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.task_type !== undefined) {
            body['task_type'] = params.task_type
        }
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        if (params.training_population !== undefined) {
            body['training_population'] = params.training_population
        }
        if (params.inference_population !== undefined) {
            body['inference_population'] = params.inference_population
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.autonomy !== undefined) {
            body['autonomy'] = params.autonomy
        }
        if (params.inference_cadence !== undefined) {
            body['inference_cadence'] = params.inference_cadence
        }
        if (params.retraining_cadence !== undefined) {
            body['retraining_cadence'] = params.retraining_cadence
        }
        if (params.output_property_name !== undefined) {
            body['output_property_name'] = params.output_property_name
        }
        const result = await context.api.request<Schemas.AutoMLPipelineDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/`,
            body,
        })
        return result
    },
})

const AutomlUpdateSchema = AutomlPipelinesPartialUpdateParams.omit({ project_id: true }).extend(
    AutomlPipelinesPartialUpdateBody.shape
)

const automlUpdate = (): ToolBase<typeof AutomlUpdateSchema, WithPostHogUrl<Schemas.AutoMLPipelineDTO>> => ({
    name: 'automl-update',
    schema: AutomlUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.autonomy !== undefined) {
            body['autonomy'] = params.autonomy
        }
        if (params.inference_cadence !== undefined) {
            body['inference_cadence'] = params.inference_cadence
        }
        if (params.retraining_cadence !== undefined) {
            body['retraining_cadence'] = params.retraining_cadence
        }
        if (params.output_property_name !== undefined) {
            body['output_property_name'] = params.output_property_name
        }
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        if (params.training_population !== undefined) {
            body['training_population'] = params.training_population
        }
        if (params.inference_population !== undefined) {
            body['inference_population'] = params.inference_population
        }
        if (params.extra !== undefined) {
            body['extra'] = params.extra
        }
        const result = await context.api.request<Schemas.AutoMLPipelineDTO>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/automl/${result.id}`)
    },
})

const AutomlStartSchema = AutomlPipelinesStartCreateParams.omit({ project_id: true })

const automlStart = (): ToolBase<typeof AutomlStartSchema, WithPostHogUrl<Schemas.AutoMLPipelineDTO>> => ({
    name: 'automl-start',
    schema: AutomlStartSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlStartSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoMLPipelineDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/start/`,
        })
        return await withPostHogUrl(context, result, `/automl/${result.id}`)
    },
})

const AutomlPauseSchema = AutomlPipelinesPauseCreateParams.omit({ project_id: true })

const automlPause = (): ToolBase<typeof AutomlPauseSchema, WithPostHogUrl<Schemas.AutoMLPipelineDTO>> => ({
    name: 'automl-pause',
    schema: AutomlPauseSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlPauseSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoMLPipelineDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/pause/`,
        })
        return await withPostHogUrl(context, result, `/automl/${result.id}`)
    },
})

const AutomlResumeSchema = AutomlPipelinesResumeCreateParams.omit({ project_id: true })

const automlResume = (): ToolBase<typeof AutomlResumeSchema, WithPostHogUrl<Schemas.AutoMLPipelineDTO>> => ({
    name: 'automl-resume',
    schema: AutomlResumeSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlResumeSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoMLPipelineDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/resume/`,
        })
        return await withPostHogUrl(context, result, `/automl/${result.id}`)
    },
})

const AutomlValidateSchema = AutomlPipelinesValidateCreateBody.extend({
    name: AutomlPipelinesValidateCreateBody.shape['name'].describe(
        'Human-readable label for the pipeline (only used by structural checks like output property name conventions). Use the same value you intend to pass to automl-create.'
    ),
    task_type: AutomlPipelinesValidateCreateBody.shape['task_type'].describe(
        'Task type the pipeline targets. Validation rules dispatch on this — classification runs the positive base-rate check, forecasting counts distinct series, clustering sanity-checks cluster_count against training-set size.'
    ),
    config: AutomlPipelinesValidateCreateBody.shape['config'].describe(
        'Task-type-specific configuration to validate. Classification expects target_event + horizon_days. Regression expects target_expression + horizon_days. Forecasting expects series_expression + grain + horizon_steps. Clustering accepts cluster_count.'
    ),
    training_population: AutomlPipelinesValidateCreateBody.shape['training_population'].describe(
        'Population definition to size for training. Only kind="hogql" populations are sized by data-touching checks; other shapes are accepted but flagged as not-counted.'
    ),
    inference_population: AutomlPipelinesValidateCreateBody.shape['inference_population'].describe(
        'Population definition used to estimate events-per-day output. Same kind="hogql" constraint as training_population.'
    ),
    inference_cadence: AutomlPipelinesValidateCreateBody.shape['inference_cadence'].describe(
        'How often inference runs. Used to project daily prediction event volume against the inference population size.'
    ),
    retraining_cadence: AutomlPipelinesValidateCreateBody.shape['retraining_cadence'].describe(
        'How often the model is refit. Compared against inference_cadence — info finding when retraining is more frequent than inference.'
    ),
    autonomy: AutomlPipelinesValidateCreateBody.shape['autonomy'].describe(
        "Output gate. Validation doesn't gate on autonomy itself; it's accepted as part of the request body so the same payload works for automl-create."
    ),
    output_property_name: AutomlPipelinesValidateCreateBody.shape['output_property_name'].describe(
        'Property name predictions are written to. Validation checks the naming convention (recommended "automl_" prefix; reserved "$" prefix is blocked).'
    ),
})

const automlValidate = (): ToolBase<typeof AutomlValidateSchema, Schemas.ValidationReport> => ({
    name: 'automl-validate',
    schema: AutomlValidateSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlValidateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.task_type !== undefined) {
            body['task_type'] = params.task_type
        }
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        if (params.training_population !== undefined) {
            body['training_population'] = params.training_population
        }
        if (params.inference_population !== undefined) {
            body['inference_population'] = params.inference_population
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.autonomy !== undefined) {
            body['autonomy'] = params.autonomy
        }
        if (params.inference_cadence !== undefined) {
            body['inference_cadence'] = params.inference_cadence
        }
        if (params.retraining_cadence !== undefined) {
            body['retraining_cadence'] = params.retraining_cadence
        }
        if (params.output_property_name !== undefined) {
            body['output_property_name'] = params.output_property_name
        }
        const result = await context.api.request<Schemas.ValidationReport>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/validate/`,
            body,
        })
        return result
    },
})

const AutomlArchiveSchema = AutomlPipelinesArchiveCreateParams.omit({ project_id: true })

const automlArchive = (): ToolBase<typeof AutomlArchiveSchema, WithPostHogUrl<Schemas.AutoMLPipelineDTO>> => ({
    name: 'automl-archive',
    schema: AutomlArchiveSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlArchiveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoMLPipelineDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/archive/`,
        })
        return await withPostHogUrl(context, result, `/automl/${result.id}`)
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'automl-list': automlList,
    'automl-get': automlGet,
    'automl-create': automlCreate,
    'automl-update': automlUpdate,
    'automl-start': automlStart,
    'automl-pause': automlPause,
    'automl-resume': automlResume,
    'automl-validate': automlValidate,
    'automl-archive': automlArchive,
}
