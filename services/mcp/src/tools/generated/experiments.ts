// AUTO-GENERATED from products/experiments/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    ExperimentsArchiveCreateParams,
    ExperimentsCreateBody,
    ExperimentsDestroyParams,
    ExperimentsDuplicateCreateBody,
    ExperimentsDuplicateCreateParams,
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
    ExperimentsTimeseriesResultsRetrieveParams,
    ExperimentsTimeseriesResultsRetrieveQueryParams,
} from '@/generated/experiments/api'
import { withUiApp } from '@/resources/ui-apps'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ExperimentListSchema = ExperimentsListQueryParams

const experimentList = (): ToolBase<typeof ExperimentListSchema, WithPostHogUrl<Schemas.PaginatedExperimentList>> =>
    withUiApp('experiment-list', {
        name: 'experiment-list',
        schema: ExperimentListSchema,
        handler: async (context: Context, params: z.infer<typeof ExperimentListSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.PaginatedExperimentList>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/`,
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
                        (filtered.results ?? []).map((item) => withPostHogUrl(context, item, `/experiments/${item.id}`))
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
                path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/${encodeURIComponent(String(params.id))}/`,
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
    type: true,
    metrics: true,
    metrics_secondary: true,
    scheduling_config: true,
    _create_in_folder: true,
    conclusion: true,
    conclusion_comment: true,
    primary_metrics_ordered_uuids: true,
    secondary_metrics_ordered_uuids: true,
    only_count_matured_users: true,
    update_feature_flag_params: true,
}).extend({
    parameters: ExperimentsCreateBody.shape['parameters'].describe(
        'Variant split and rollout scope. If the user mentions a specific percentage, load the configuring-experiment-rollout skill and clarify before setting these values. Set rollout_percentage (0-100) to control the overall fraction of users entering the experiment. Set feature_flag_variants with split_percent on each variant to customize the variant split. Default: 50/50 control/test, 100% rollout.'
    ),
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
            if (params.exposure_criteria !== undefined) {
                body['exposure_criteria'] = params.exposure_criteria
            }
            if (params.stats_config !== undefined) {
                body['stats_config'] = params.stats_config
            }
            if (params.allow_unknown_events !== undefined) {
                body['allow_unknown_events'] = params.allow_unknown_events
            }
            const result = await context.api.request<Schemas.Experiment>({
                method: 'POST',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/`,
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
        secondary_metrics: true,
        saved_metrics_ids: true,
        filters: true,
        deleted: true,
        type: true,
        exposure_criteria: true,
        scheduling_config: true,
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
            if (params.holdout_id !== undefined) {
                body['holdout_id'] = params.holdout_id
            }
            if (params.parameters !== undefined) {
                body['parameters'] = params.parameters
            }
            if (params.archived !== undefined) {
                body['archived'] = params.archived
            }
            if (params.metrics !== undefined) {
                body['metrics'] = params.metrics
            }
            if (params.metrics_secondary !== undefined) {
                body['metrics_secondary'] = params.metrics_secondary
            }
            if (params.stats_config !== undefined) {
                body['stats_config'] = params.stats_config
            }
            if (params.allow_unknown_events !== undefined) {
                body['allow_unknown_events'] = params.allow_unknown_events
            }
            if (params.conclusion !== undefined) {
                body['conclusion'] = params.conclusion
            }
            if (params.conclusion_comment !== undefined) {
                body['conclusion_comment'] = params.conclusion_comment
            }
            if (params.update_feature_flag_params !== undefined) {
                body['update_feature_flag_params'] = params.update_feature_flag_params
            }
            const result = await context.api.request<Schemas.Experiment>({
                method: 'PATCH',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/${encodeURIComponent(String(params.id))}/`,
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/${encodeURIComponent(String(params.id))}/`,
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
                path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/${encodeURIComponent(String(params.id))}/launch/`,
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
                path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/${encodeURIComponent(String(params.id))}/end/`,
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
                path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/${encodeURIComponent(String(params.id))}/archive/`,
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
                path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/${encodeURIComponent(String(params.id))}/ship_variant/`,
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
                path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/${encodeURIComponent(String(params.id))}/pause/`,
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
                path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/${encodeURIComponent(String(params.id))}/resume/`,
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
                path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/${encodeURIComponent(String(params.id))}/reset/`,
            })
            return await withPostHogUrl(context, result, `/experiments/${result.id}`)
        },
    })

const ExperimentTimeseriesResultsSchema = ExperimentsTimeseriesResultsRetrieveParams.omit({ project_id: true }).extend(
    ExperimentsTimeseriesResultsRetrieveQueryParams.shape
)

const experimentTimeseriesResults = (): ToolBase<typeof ExperimentTimeseriesResultsSchema, unknown> =>
    withUiApp('experiment-results', {
        name: 'experiment-timeseries-results',
        schema: ExperimentTimeseriesResultsSchema,
        handler: async (context: Context, params: z.infer<typeof ExperimentTimeseriesResultsSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<unknown>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/${encodeURIComponent(String(params.id))}/timeseries_results/`,
                query: {
                    fingerprint: params.fingerprint,
                    metric_uuid: params.metric_uuid,
                },
            })
            return result
        },
    })

const ExperimentStatsSchema = z.object({})

const experimentStats = (): ToolBase<typeof ExperimentStatsSchema, unknown> => ({
    name: 'experiment-stats',
    schema: ExperimentStatsSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof ExperimentStatsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/stats/`,
        })
        return result
    },
})

const ExperimentDuplicateSchema = ExperimentsDuplicateCreateParams.omit({ project_id: true }).extend(
    ExperimentsDuplicateCreateBody.omit({ _create_in_folder: true }).shape
)

const experimentDuplicate = (): ToolBase<typeof ExperimentDuplicateSchema, unknown> => ({
    name: 'experiment-duplicate',
    schema: ExperimentDuplicateSchema,
    handler: async (context: Context, params: z.infer<typeof ExperimentDuplicateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.start_date !== undefined) {
            body['start_date'] = params.start_date
        }
        if (params.end_date !== undefined) {
            body['end_date'] = params.end_date
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
        if (params.secondary_metrics !== undefined) {
            body['secondary_metrics'] = params.secondary_metrics
        }
        if (params.saved_metrics_ids !== undefined) {
            body['saved_metrics_ids'] = params.saved_metrics_ids
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.archived !== undefined) {
            body['archived'] = params.archived
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
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
        if (params.stats_config !== undefined) {
            body['stats_config'] = params.stats_config
        }
        if (params.scheduling_config !== undefined) {
            body['scheduling_config'] = params.scheduling_config
        }
        if (params.allow_unknown_events !== undefined) {
            body['allow_unknown_events'] = params.allow_unknown_events
        }
        if (params.conclusion !== undefined) {
            body['conclusion'] = params.conclusion
        }
        if (params.conclusion_comment !== undefined) {
            body['conclusion_comment'] = params.conclusion_comment
        }
        if (params.primary_metrics_ordered_uuids !== undefined) {
            body['primary_metrics_ordered_uuids'] = params.primary_metrics_ordered_uuids
        }
        if (params.secondary_metrics_ordered_uuids !== undefined) {
            body['secondary_metrics_ordered_uuids'] = params.secondary_metrics_ordered_uuids
        }
        if (params.only_count_matured_users !== undefined) {
            body['only_count_matured_users'] = params.only_count_matured_users
        }
        if (params.update_feature_flag_params !== undefined) {
            body['update_feature_flag_params'] = params.update_feature_flag_params
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/${encodeURIComponent(String(params.id))}/duplicate/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'experiment-list': experimentList,
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
    'experiment-timeseries-results': experimentTimeseriesResults,
    'experiment-stats': experimentStats,
    'experiment-duplicate': experimentDuplicate,
}
