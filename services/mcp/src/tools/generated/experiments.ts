// AUTO-GENERATED from products/experiments/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    ExperimentsArchiveCreateParams,
    ExperimentsCreateBody,
    ExperimentsDestroyParams,
    ExperimentsEndCreateBody,
    ExperimentsEndCreateParams,
    ExperimentsLaunchCreateParams,
    ExperimentsListQueryParams,
    ExperimentsPartialUpdateBody,
    ExperimentsPartialUpdateParams,
    ExperimentsPauseCreateParams,
    ExperimentsResetCreateParams,
    ExperimentsResumeCreateParams,
    ExperimentsRetrieveParams,
    ExperimentsShipVariantCreateBody,
    ExperimentsShipVariantCreateParams,
} from '@/generated/experiments/api'
import { withUiApp } from '@/resources/ui-apps'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ExperimentGetAllSchema = ExperimentsListQueryParams

const experimentGetAll = (): ToolBase<typeof ExperimentGetAllSchema, WithPostHogUrl<Schemas.PaginatedExperimentList>> =>
    withUiApp('experiment-list', {
        name: 'experiment-get-all',
        schema: ExperimentGetAllSchema,
        handler: async (context: Context, params: z.infer<typeof ExperimentGetAllSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.PaginatedExperimentList>({
                method: 'GET',
                path: `/api/projects/${projectId}/experiments/`,
                query: {
                    limit: params.limit,
                    offset: params.offset,
                },
            })
            const filtered = {
                ...result,
                results: result.results.map((item: any) =>
                    pickResponseFields(item, [
                        'id',
                        'name',
                        'description',
                        'feature_flag_key',
                        'start_date',
                        'end_date',
                        'archived',
                        'type',
                        'status',
                        'created_at',
                        'updated_at',
                    ])
                ),
            } as typeof result
            return await withPostHogUrl(
                context,
                {
                    ...filtered,
                    results: await Promise.all(
                        filtered.results.map((item) => withPostHogUrl(context, item, `/experiments/${item.id}`))
                    ),
                },
                '/experiments'
            )
        },
    })

const ExperimentGetSchema = ExperimentsRetrieveParams.omit({ project_id: true })

const experimentGet = (): ToolBase<typeof ExperimentGetSchema, WithPostHogUrl<Schemas.Experiment>> =>
    withUiApp('experiment', {
        name: 'experiment-get',
        schema: ExperimentGetSchema,
        handler: async (context: Context, params: z.infer<typeof ExperimentGetSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.Experiment>({
                method: 'GET',
                path: `/api/projects/${projectId}/experiments/${params.id}/`,
            })
            return await withPostHogUrl(context, result, `/experiments/${result.id}`)
        },
    })

const ExperimentCreateSchema = ExperimentsCreateBody.omit({
    start_date: true,
    end_date: true,
    secondary_metrics: true,
    saved_metrics_ids: true,
    filters: true,
    archived: true,
    deleted: true,
    stats_config: true,
    scheduling_config: true,
    _create_in_folder: true,
    conclusion: true,
    conclusion_comment: true,
    primary_metrics_ordered_uuids: true,
    secondary_metrics_ordered_uuids: true,
    only_count_matured_users: true,
})

const experimentCreate = (): ToolBase<typeof ExperimentCreateSchema, WithPostHogUrl<Schemas.Experiment>> =>
    withUiApp('experiment', {
        name: 'experiment-create',
        schema: ExperimentCreateSchema,
        handler: async (context: Context, params: z.infer<typeof ExperimentCreateSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const body: Record<string, unknown> = {}
            if (params.name !== undefined) {
                body['name'] = params.name
            }
            if (params.description !== undefined) {
                body['description'] = params.description
            }
            if (params.feature_flag_key !== undefined) {
                body['feature_flag_key'] = params.feature_flag_key
            }
            if (params.holdout_id !== undefined) {
                body['holdout_id'] = params.holdout_id
            }
            if (params.parameters !== undefined) {
                body['parameters'] = params.parameters
            }
            if (params.type !== undefined) {
                body['type'] = params.type
            }
            if (params.exposure_criteria !== undefined) {
                body['exposure_criteria'] = params.exposure_criteria
            }
            if (params.metrics !== undefined) {
                body['metrics'] = params.metrics
            }
            if (params.metrics_secondary !== undefined) {
                body['metrics_secondary'] = params.metrics_secondary
            }
            if (params.allow_unknown_events !== undefined) {
                body['allow_unknown_events'] = params.allow_unknown_events
            }
            const result = await context.api.request<Schemas.Experiment>({
                method: 'POST',
                path: `/api/projects/${projectId}/experiments/`,
                body,
            })
            return await withPostHogUrl(context, result, `/experiments/${result.id}`)
        },
    })

const ExperimentUpdateSchema = ExperimentsPartialUpdateParams.omit({ project_id: true }).extend(
    ExperimentsPartialUpdateBody.omit({
        start_date: true,
        end_date: true,
        feature_flag_key: true,
        holdout_id: true,
        secondary_metrics: true,
        saved_metrics_ids: true,
        filters: true,
        deleted: true,
        type: true,
        stats_config: true,
        scheduling_config: true,
        allow_unknown_events: true,
        _create_in_folder: true,
        primary_metrics_ordered_uuids: true,
        secondary_metrics_ordered_uuids: true,
        only_count_matured_users: true,
    }).shape
)

const experimentUpdate = (): ToolBase<typeof ExperimentUpdateSchema, WithPostHogUrl<Schemas.Experiment>> =>
    withUiApp('experiment', {
        name: 'experiment-update',
        schema: ExperimentUpdateSchema,
        handler: async (context: Context, params: z.infer<typeof ExperimentUpdateSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const body: Record<string, unknown> = {}
            if (params.name !== undefined) {
                body['name'] = params.name
            }
            if (params.description !== undefined) {
                body['description'] = params.description
            }
            if (params.parameters !== undefined) {
                body['parameters'] = params.parameters
            }
            if (params.archived !== undefined) {
                body['archived'] = params.archived
            }
            if (params.exposure_criteria !== undefined) {
                body['exposure_criteria'] = params.exposure_criteria
            }
            if (params.metrics !== undefined) {
                body['metrics'] = params.metrics
            }
            if (params.metrics_secondary !== undefined) {
                body['metrics_secondary'] = params.metrics_secondary
            }
            if (params.conclusion !== undefined) {
                body['conclusion'] = params.conclusion
            }
            if (params.conclusion_comment !== undefined) {
                body['conclusion_comment'] = params.conclusion_comment
            }
            const result = await context.api.request<Schemas.Experiment>({
                method: 'PATCH',
                path: `/api/projects/${projectId}/experiments/${params.id}/`,
                body,
            })
            return await withPostHogUrl(context, result, `/experiments/${result.id}`)
        },
    })

const ExperimentDeleteSchema = ExperimentsDestroyParams.omit({ project_id: true })

const experimentDelete = (): ToolBase<typeof ExperimentDeleteSchema, Schemas.Experiment> => ({
    name: 'experiment-delete',
    schema: ExperimentDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof ExperimentDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Experiment>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/experiments/${params.id}/`,
            body: { deleted: true },
        })
        const filtered = pickResponseFields(result, ['id', 'name', 'deleted']) as typeof result
        return filtered
    },
})

const ExperimentLaunchSchema = ExperimentsLaunchCreateParams.omit({ project_id: true })

const experimentLaunch = (): ToolBase<typeof ExperimentLaunchSchema, WithPostHogUrl<Schemas.Experiment>> =>
    withUiApp('experiment', {
        name: 'experiment-launch',
        schema: ExperimentLaunchSchema,
        handler: async (context: Context, params: z.infer<typeof ExperimentLaunchSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.Experiment>({
                method: 'POST',
                path: `/api/projects/${projectId}/experiments/${params.id}/launch/`,
            })
            return await withPostHogUrl(context, result, `/experiments/${result.id}`)
        },
    })

const ExperimentEndSchema = ExperimentsEndCreateParams.omit({ project_id: true }).extend(ExperimentsEndCreateBody.shape)

const experimentEnd = (): ToolBase<typeof ExperimentEndSchema, WithPostHogUrl<Schemas.Experiment>> =>
    withUiApp('experiment', {
        name: 'experiment-end',
        schema: ExperimentEndSchema,
        handler: async (context: Context, params: z.infer<typeof ExperimentEndSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const body: Record<string, unknown> = {}
            if (params.conclusion !== undefined) {
                body['conclusion'] = params.conclusion
            }
            if (params.conclusion_comment !== undefined) {
                body['conclusion_comment'] = params.conclusion_comment
            }
            const result = await context.api.request<Schemas.Experiment>({
                method: 'POST',
                path: `/api/projects/${projectId}/experiments/${params.id}/end/`,
                body,
            })
            return await withPostHogUrl(context, result, `/experiments/${result.id}`)
        },
    })

const ExperimentArchiveSchema = ExperimentsArchiveCreateParams.omit({ project_id: true })

const experimentArchive = (): ToolBase<typeof ExperimentArchiveSchema, WithPostHogUrl<Schemas.Experiment>> =>
    withUiApp('experiment', {
        name: 'experiment-archive',
        schema: ExperimentArchiveSchema,
        handler: async (context: Context, params: z.infer<typeof ExperimentArchiveSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.Experiment>({
                method: 'POST',
                path: `/api/projects/${projectId}/experiments/${params.id}/archive/`,
            })
            return await withPostHogUrl(context, result, `/experiments/${result.id}`)
        },
    })

const ExperimentShipVariantSchema = ExperimentsShipVariantCreateParams.omit({ project_id: true }).extend(
    ExperimentsShipVariantCreateBody.shape
)

const experimentShipVariant = (): ToolBase<typeof ExperimentShipVariantSchema, WithPostHogUrl<Schemas.Experiment>> =>
    withUiApp('experiment', {
        name: 'experiment-ship-variant',
        schema: ExperimentShipVariantSchema,
        handler: async (context: Context, params: z.infer<typeof ExperimentShipVariantSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const body: Record<string, unknown> = {}
            if (params.conclusion !== undefined) {
                body['conclusion'] = params.conclusion
            }
            if (params.conclusion_comment !== undefined) {
                body['conclusion_comment'] = params.conclusion_comment
            }
            if (params.variant_key !== undefined) {
                body['variant_key'] = params.variant_key
            }
            const result = await context.api.request<Schemas.Experiment>({
                method: 'POST',
                path: `/api/projects/${projectId}/experiments/${params.id}/ship_variant/`,
                body,
            })
            return await withPostHogUrl(context, result, `/experiments/${result.id}`)
        },
    })

const ExperimentPauseSchema = ExperimentsPauseCreateParams.omit({ project_id: true })

const experimentPause = (): ToolBase<typeof ExperimentPauseSchema, WithPostHogUrl<Schemas.Experiment>> =>
    withUiApp('experiment', {
        name: 'experiment-pause',
        schema: ExperimentPauseSchema,
        handler: async (context: Context, params: z.infer<typeof ExperimentPauseSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.Experiment>({
                method: 'POST',
                path: `/api/projects/${projectId}/experiments/${params.id}/pause/`,
            })
            return await withPostHogUrl(context, result, `/experiments/${result.id}`)
        },
    })

const ExperimentResumeSchema = ExperimentsResumeCreateParams.omit({ project_id: true })

const experimentResume = (): ToolBase<typeof ExperimentResumeSchema, WithPostHogUrl<Schemas.Experiment>> =>
    withUiApp('experiment', {
        name: 'experiment-resume',
        schema: ExperimentResumeSchema,
        handler: async (context: Context, params: z.infer<typeof ExperimentResumeSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.Experiment>({
                method: 'POST',
                path: `/api/projects/${projectId}/experiments/${params.id}/resume/`,
            })
            return await withPostHogUrl(context, result, `/experiments/${result.id}`)
        },
    })

const ExperimentResetSchema = ExperimentsResetCreateParams.omit({ project_id: true })

const experimentReset = (): ToolBase<typeof ExperimentResetSchema, WithPostHogUrl<Schemas.Experiment>> =>
    withUiApp('experiment', {
        name: 'experiment-reset',
        schema: ExperimentResetSchema,
        handler: async (context: Context, params: z.infer<typeof ExperimentResetSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.Experiment>({
                method: 'POST',
                path: `/api/projects/${projectId}/experiments/${params.id}/reset/`,
            })
            return await withPostHogUrl(context, result, `/experiments/${result.id}`)
        },
    })

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'experiment-get-all': experimentGetAll,
    'experiment-get': experimentGet,
    'experiment-create': experimentCreate,
    'experiment-update': experimentUpdate,
    'experiment-delete': experimentDelete,
    'experiment-launch': experimentLaunch,
    'experiment-end': experimentEnd,
    'experiment-archive': experimentArchive,
    'experiment-ship-variant': experimentShipVariant,
    'experiment-pause': experimentPause,
    'experiment-resume': experimentResume,
    'experiment-reset': experimentReset,
}
