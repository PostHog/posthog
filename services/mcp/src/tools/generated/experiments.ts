// AUTO-GENERATED from products/experiments/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    ExperimentHoldoutsCreateBody,
    ExperimentHoldoutsDestroyParams,
    ExperimentHoldoutsListQueryParams,
    ExperimentHoldoutsPartialUpdateBody,
    ExperimentHoldoutsPartialUpdateParams,
    ExperimentHoldoutsRetrieveParams,
    ExperimentSavedMetricsCreateBody,
    ExperimentSavedMetricsDestroyParams,
    ExperimentSavedMetricsListQueryParams,
    ExperimentSavedMetricsPartialUpdateBody,
    ExperimentSavedMetricsPartialUpdateParams,
    ExperimentSavedMetricsRetrieveParams,
    ExperimentsArchiveCreateBody,
    ExperimentsArchiveCreateParams,
    ExperimentsCalculateRunningTimeCreateBody,
    ExperimentsCopyToProjectCreateBody,
    ExperimentsCopyToProjectCreateParams,
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
    ExperimentsUnarchiveCreateParams,
} from '@/generated/experiments/api'
import { withUiApp } from '@/resources/ui-apps'
import { SavedMetricsAttachSchema } from '@/schema/tool-inputs'
import { castStringToInt } from '@/tools/cast-helpers'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ExperimentArchiveSchema = ExperimentsArchiveCreateParams.omit({ project_id: true })
    .extend(ExperimentsArchiveCreateBody.shape)
    .extend({ id: z.preprocess(castStringToInt, ExperimentsArchiveCreateParams.shape['id']) })

const experimentArchive = (): ToolBase<typeof ExperimentArchiveSchema, WithPostHogUrl<Schemas.Experiment>> =>
    withUiApp('experiment', {
        name: 'experiment-archive',
        schema: ExperimentArchiveSchema,
        handler: async (context: Context, params: z.infer<typeof ExperimentArchiveSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const body: Record<string, unknown> = {}
            if (params.disable_feature_flag !== undefined) {
                body['disable_feature_flag'] = params.disable_feature_flag
            }
            const result = await context.api.request<Schemas.Experiment>({
                method: 'POST',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/${encodeURIComponent(String(params.id))}/archive/`,
                body,
            })
            return await withPostHogUrl(context, result, `/experiments/${result.id}`)
        },
    })

const ExperimentCalculateRunningTimeSchema = ExperimentsCalculateRunningTimeCreateBody

const experimentCalculateRunningTime = (): ToolBase<
    typeof ExperimentCalculateRunningTimeSchema,
    Schemas.RunningTimeCalculationResult
> => ({
    name: 'experiment-calculate-running-time',
    schema: ExperimentCalculateRunningTimeSchema,
    handler: async (context: Context, params: z.infer<typeof ExperimentCalculateRunningTimeSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.metric_type !== undefined) {
            body['metric_type'] = params.metric_type
        }
        if (params.minimum_detectable_effect !== undefined) {
            body['minimum_detectable_effect'] = params.minimum_detectable_effect
        }
        if (params.number_of_variants !== undefined) {
            body['number_of_variants'] = params.number_of_variants
        }
        if (params.exposure_rate_per_day !== undefined) {
            body['exposure_rate_per_day'] = params.exposure_rate_per_day
        }
        if (params.baseline_value !== undefined) {
            body['baseline_value'] = params.baseline_value
        }
        if (params.variance !== undefined) {
            body['variance'] = params.variance
        }
        if (params.baseline_stats !== undefined) {
            body['baseline_stats'] = params.baseline_stats
        }
        const result = await context.api.request<Schemas.RunningTimeCalculationResult>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/calculate_running_time/`,
            body,
        })
        return result
    },
})

const ExperimentCopyToProjectSchema = ExperimentsCopyToProjectCreateParams.omit({ project_id: true })
    .extend(ExperimentsCopyToProjectCreateBody.shape)
    .extend({
        id: z.preprocess(castStringToInt, ExperimentsCopyToProjectCreateParams.shape['id']),
        target_team_id: z.preprocess(castStringToInt, ExperimentsCopyToProjectCreateBody.shape['target_team_id']),
    })

const experimentCopyToProject = (): ToolBase<typeof ExperimentCopyToProjectSchema, Schemas.Experiment> => ({
    name: 'experiment-copy-to-project',
    schema: ExperimentCopyToProjectSchema,
    handler: async (context: Context, params: z.infer<typeof ExperimentCopyToProjectSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.target_team_id !== undefined) {
            body['target_team_id'] = params.target_team_id
        }
        if (params.feature_flag_key !== undefined) {
            body['feature_flag_key'] = params.feature_flag_key
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        const result = await context.api.request<Schemas.Experiment>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/${encodeURIComponent(String(params.id))}/copy_to_project/`,
            body,
        })
        const filtered = pickResponseFields(result, [
            'id',
            'name',
            'description',
            'type',
            'feature_flag_key',
            'status',
            'archived',
            'start_date',
            'end_date',
            'created_at',
            'parameters',
            'metrics',
            'metrics_secondary',
            'conclusion',
            'conclusion_comment',
        ]) as typeof result
        return filtered
    },
})

const ExperimentCreateSchema = ExperimentsCreateBody.omit({
    start_date: true,
    end_date: true,
    running_time_calculation: true,
    excluded_variants: true,
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
    feature_flag: ExperimentsCreateBody.shape['feature_flag'].describe(
        'Variant split, rollout scope, payloads, and experience continuity for the auto-created feature flag, in the flag\'s own filters shape. This is the canonical input, do not send flag config via the deprecated parameters keys (feature_flag_variants, rollout_percentage). If the user mentions a specific percentage, load the configuring-experiment-rollout skill and clarify before setting these values. Set filters.multivariate.variants (each with key and rollout_percentage; percentages must sum to 100) to customize the variant split. Set filters.groups to a single group [{"properties": [], "rollout_percentage": N}] (0-100) to control the overall fraction of users entering the experiment. Default: 50/50 control/test, 100% rollout. Omit this parameter entirely when feature_flag_key refers to a pre-existing flag: the experiment links to that flag as-is and explicit config is rejected. HARD REQUIREMENT — when you provide variants, exactly one variant\'s `key` must be the literal string `control` (lowercase, no variations). It is the baseline used for analysis and the experiment runtime treats it specially. If the user describes variants as "A/B", "old/new", "original/redesign", or any other natural-language pair, map the baseline to `key: "control"` — not "A", "Control", "old", "original", or "baseline". Other variants can use any key (`test`, `variant_a`, etc.).'
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
            if (params.feature_flag !== undefined) {
                body['feature_flag'] = params.feature_flag
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
            const filtered = pickResponseFields(result, [
                'id',
                'name',
                'description',
                'type',
                'feature_flag_key',
                'status',
                'archived',
                'start_date',
                'end_date',
                'created_at',
                'parameters',
                'metrics',
                'metrics_secondary',
                'conclusion',
                'conclusion_comment',
            ]) as typeof result
            return await withPostHogUrl(context, filtered, `/experiments/${filtered.id}`)
        },
    })

const ExperimentDeleteSchema = ExperimentsDestroyParams.omit({ project_id: true }).extend({
    id: z.preprocess(castStringToInt, ExperimentsDestroyParams.shape['id']),
})

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

const ExperimentDuplicateSchema = ExperimentsDuplicateCreateParams.omit({ project_id: true })
    .extend(
        ExperimentsDuplicateCreateBody.omit({
            description: true,
            start_date: true,
            end_date: true,
            holdout_id: true,
            parameters: true,
            running_time_calculation: true,
            excluded_variants: true,
            secondary_metrics: true,
            saved_metrics_ids: true,
            filters: true,
            archived: true,
            deleted: true,
            type: true,
            exposure_criteria: true,
            metrics: true,
            metrics_secondary: true,
            stats_config: true,
            scheduling_config: true,
            allow_unknown_events: true,
            _create_in_folder: true,
            conclusion: true,
            conclusion_comment: true,
            primary_metrics_ordered_uuids: true,
            secondary_metrics_ordered_uuids: true,
            only_count_matured_users: true,
            update_feature_flag_params: true,
        }).shape
    )
    .extend({ id: z.preprocess(castStringToInt, ExperimentsDuplicateCreateParams.shape['id']) })

const experimentDuplicate = (): ToolBase<typeof ExperimentDuplicateSchema, unknown> => ({
    name: 'experiment-duplicate',
    schema: ExperimentDuplicateSchema,
    handler: async (context: Context, params: z.infer<typeof ExperimentDuplicateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.feature_flag_key !== undefined) {
            body['feature_flag_key'] = params.feature_flag_key
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/${encodeURIComponent(String(params.id))}/duplicate/`,
            body,
        })
        return result
    },
})

const ExperimentEndSchema = ExperimentsEndCreateParams.omit({ project_id: true })
    .extend(ExperimentsEndCreateBody.shape)
    .extend({ id: z.preprocess(castStringToInt, ExperimentsEndCreateParams.shape['id']) })

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
            if (params.open_cleanup_pr !== undefined) {
                body['open_cleanup_pr'] = params.open_cleanup_pr
            }
            const result = await context.api.request<Schemas.Experiment>({
                method: 'POST',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/${encodeURIComponent(String(params.id))}/end/`,
                body,
            })
            return await withPostHogUrl(context, result, `/experiments/${result.id}`)
        },
    })

const ExperimentGetSchema = ExperimentsRetrieveParams.omit({ project_id: true }).extend({
    id: z.preprocess(castStringToInt, ExperimentsRetrieveParams.shape['id']),
})

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

const ExperimentHoldoutsCreateSchema = ExperimentHoldoutsCreateBody.extend({
    filters: ExperimentHoldoutsCreateBody.shape['filters'].describe(
        'Non-empty list of release-condition groups defining the held-out population. Each element needs a `rollout_percentage` (0–100, may be fractional) — this is the EXCLUSION percentage, i.e. the share of users held back from every experiment that references this holdout. `properties` optionally narrows the group by person/group properties (same shape as feature-flag release conditions); pass an empty array for an unconditional holdout. Do NOT set `variant` — the server sets it to `holdout-{id}` automatically. Only the first element\'s `rollout_percentage` is embedded into each linked experiment\'s feature flag. Example: [{ "rollout_percentage": 10, "properties": [] }].'
    ),
})

const experimentHoldoutsCreate = (): ToolBase<typeof ExperimentHoldoutsCreateSchema, Schemas.ExperimentHoldout> => ({
    name: 'experiment-holdouts-create',
    schema: ExperimentHoldoutsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ExperimentHoldoutsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        const result = await context.api.request<Schemas.ExperimentHoldout>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/experiment_holdouts/`,
            body,
        })
        return result
    },
})

const ExperimentHoldoutsDestroySchema = ExperimentHoldoutsDestroyParams.omit({ project_id: true }).extend({
    id: z.preprocess(castStringToInt, ExperimentHoldoutsDestroyParams.shape['id']),
})

const experimentHoldoutsDestroy = (): ToolBase<typeof ExperimentHoldoutsDestroySchema, unknown> => ({
    name: 'experiment-holdouts-destroy',
    schema: ExperimentHoldoutsDestroySchema,
    handler: async (context: Context, params: z.infer<typeof ExperimentHoldoutsDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/experiment_holdouts/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const ExperimentHoldoutsListSchema = ExperimentHoldoutsListQueryParams

const experimentHoldoutsList = (): ToolBase<
    typeof ExperimentHoldoutsListSchema,
    WithPostHogUrl<Schemas.PaginatedExperimentHoldoutList>
> => ({
    name: 'experiment-holdouts-list',
    schema: ExperimentHoldoutsListSchema,
    handler: async (context: Context, params: z.infer<typeof ExperimentHoldoutsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedExperimentHoldoutList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/experiment_holdouts/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, ['id', 'name', 'description', 'filters', 'created_at', 'updated_at'])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/experiments')
    },
})

const ExperimentHoldoutsPartialUpdateSchema = ExperimentHoldoutsPartialUpdateParams.omit({ project_id: true })
    .extend(ExperimentHoldoutsPartialUpdateBody.shape)
    .extend({
        id: z.preprocess(castStringToInt, ExperimentHoldoutsPartialUpdateParams.shape['id']),
        filters: ExperimentHoldoutsPartialUpdateBody.shape['filters'].describe(
            'Non-empty list of release-condition groups defining the held-out population. Each element needs a `rollout_percentage` (0–100, may be fractional) — the EXCLUSION percentage. Do NOT set `variant` (the server manages it as `holdout-{id}`). Changing this cascades to every linked experiment\'s feature flag. Example: [{ "rollout_percentage": 10, "properties": [] }].'
        ),
    })

const experimentHoldoutsPartialUpdate = (): ToolBase<
    typeof ExperimentHoldoutsPartialUpdateSchema,
    Schemas.ExperimentHoldout
> => ({
    name: 'experiment-holdouts-partial-update',
    schema: ExperimentHoldoutsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof ExperimentHoldoutsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        const result = await context.api.request<Schemas.ExperimentHoldout>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/experiment_holdouts/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const ExperimentHoldoutsRetrieveSchema = ExperimentHoldoutsRetrieveParams.omit({ project_id: true }).extend({
    id: z.preprocess(castStringToInt, ExperimentHoldoutsRetrieveParams.shape['id']),
})

const experimentHoldoutsRetrieve = (): ToolBase<
    typeof ExperimentHoldoutsRetrieveSchema,
    Schemas.ExperimentHoldout
> => ({
    name: 'experiment-holdouts-retrieve',
    schema: ExperimentHoldoutsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof ExperimentHoldoutsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ExperimentHoldout>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/experiment_holdouts/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const ExperimentLaunchSchema = ExperimentsLaunchCreateParams.omit({ project_id: true }).extend({
    id: z.preprocess(castStringToInt, ExperimentsLaunchCreateParams.shape['id']),
})

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
            const filtered = pickResponseFields(result, [
                'id',
                'name',
                'description',
                'type',
                'feature_flag_key',
                'status',
                'archived',
                'start_date',
                'end_date',
                'created_at',
                'parameters',
                'metrics',
                'metrics_secondary',
                'conclusion',
                'conclusion_comment',
            ]) as typeof result
            return await withPostHogUrl(context, filtered, `/experiments/${filtered.id}`)
        },
    })

const ExperimentListSchema = ExperimentsListQueryParams.extend({
    status: ExperimentsListQueryParams.shape['status'].describe(
        'Filter by experiment status. Values: "draft" (not yet launched), "running" (launched, flag active), "paused" (launched, flag deactivated — mutually exclusive with running), "exposure_frozen" (launched, enrollment frozen to the already-exposed cohort while metrics keep flowing), "stopped" or "complete" (both mean ended), "all" (no filter). Defaults to all non-archived experiments.'
    ),
    limit: z.preprocess(castStringToInt, ExperimentsListQueryParams.shape['limit']).optional(),
    offset: z.preprocess(castStringToInt, ExperimentsListQueryParams.shape['offset']).optional(),
    feature_flag_id: z.preprocess(castStringToInt, ExperimentsListQueryParams.shape['feature_flag_id']).optional(),
})

const experimentList = (): ToolBase<
    typeof ExperimentListSchema,
    WithPostHogUrl<Schemas.PaginatedExperimentBasicList>
> =>
    withUiApp('experiment-list', {
        name: 'experiment-list',
        schema: ExperimentListSchema,
        handler: async (context: Context, params: z.infer<typeof ExperimentListSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.PaginatedExperimentBasicList>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/`,
                query: {
                    archived: params.archived,
                    created_by_id: params.created_by_id,
                    event: params.event,
                    feature_flag_id: params.feature_flag_id,
                    limit: params.limit,
                    offset: params.offset,
                    order: params.order,
                    prompt_name: params.prompt_name,
                    search: params.search,
                    status: params.status,
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
                        'feature_flag',
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

const ExperimentPauseSchema = ExperimentsPauseCreateParams.omit({ project_id: true }).extend({
    id: z.preprocess(castStringToInt, ExperimentsPauseCreateParams.shape['id']),
})

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

const ExperimentResetSchema = ExperimentsResetCreateParams.omit({ project_id: true }).extend({
    id: z.preprocess(castStringToInt, ExperimentsResetCreateParams.shape['id']),
})

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

const ExperimentResumeSchema = ExperimentsResumeCreateParams.omit({ project_id: true }).extend({
    id: z.preprocess(castStringToInt, ExperimentsResumeCreateParams.shape['id']),
})

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

const ExperimentSavedMetricsCreateSchema = ExperimentSavedMetricsCreateBody

const experimentSavedMetricsCreate = (): ToolBase<
    typeof ExperimentSavedMetricsCreateSchema,
    Schemas.ExperimentSavedMetric
> => ({
    name: 'experiment-saved-metrics-create',
    schema: ExperimentSavedMetricsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ExperimentSavedMetricsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        const result = await context.api.request<Schemas.ExperimentSavedMetric>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/experiment_saved_metrics/`,
            body,
        })
        return result
    },
})

const ExperimentSavedMetricsDestroySchema = ExperimentSavedMetricsDestroyParams.omit({ project_id: true }).extend({
    id: z.preprocess(castStringToInt, ExperimentSavedMetricsDestroyParams.shape['id']),
})

const experimentSavedMetricsDestroy = (): ToolBase<typeof ExperimentSavedMetricsDestroySchema, unknown> => ({
    name: 'experiment-saved-metrics-destroy',
    schema: ExperimentSavedMetricsDestroySchema,
    handler: async (context: Context, params: z.infer<typeof ExperimentSavedMetricsDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/experiment_saved_metrics/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const ExperimentSavedMetricsListSchema = ExperimentSavedMetricsListQueryParams.extend({
    limit: z.preprocess(castStringToInt, ExperimentSavedMetricsListQueryParams.shape['limit']).optional(),
    offset: z.preprocess(castStringToInt, ExperimentSavedMetricsListQueryParams.shape['offset']).optional(),
    event: ExperimentSavedMetricsListQueryParams.shape['event'].describe(
        "Filter to shared metrics whose query references this event name — matched directly (an EventsNode) or via the step events of any action the metric references. For finding a reusable metric by what it measures; then confirm the match against each row's 'query'."
    ),
})

const experimentSavedMetricsList = (): ToolBase<
    typeof ExperimentSavedMetricsListSchema,
    WithPostHogUrl<Schemas.PaginatedExperimentSavedMetricList>
> => ({
    name: 'experiment-saved-metrics-list',
    schema: ExperimentSavedMetricsListSchema,
    handler: async (context: Context, params: z.infer<typeof ExperimentSavedMetricsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedExperimentSavedMetricList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/experiment_saved_metrics/`,
            query: {
                event: params.event,
                limit: params.limit,
                offset: params.offset,
                search: params.search,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, ['id', 'name', 'description', 'query', 'created_at', 'updated_at', 'tags'])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/experiments')
    },
})

const ExperimentSavedMetricsPartialUpdateSchema = ExperimentSavedMetricsPartialUpdateParams.omit({ project_id: true })
    .extend(ExperimentSavedMetricsPartialUpdateBody.shape)
    .extend({ id: z.preprocess(castStringToInt, ExperimentSavedMetricsPartialUpdateParams.shape['id']) })

const experimentSavedMetricsPartialUpdate = (): ToolBase<
    typeof ExperimentSavedMetricsPartialUpdateSchema,
    Schemas.ExperimentSavedMetric
> => ({
    name: 'experiment-saved-metrics-partial-update',
    schema: ExperimentSavedMetricsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof ExperimentSavedMetricsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        const result = await context.api.request<Schemas.ExperimentSavedMetric>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/experiment_saved_metrics/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const ExperimentSavedMetricsRetrieveSchema = ExperimentSavedMetricsRetrieveParams.omit({ project_id: true }).extend({
    id: z.preprocess(castStringToInt, ExperimentSavedMetricsRetrieveParams.shape['id']),
})

const experimentSavedMetricsRetrieve = (): ToolBase<
    typeof ExperimentSavedMetricsRetrieveSchema,
    Schemas.ExperimentSavedMetric
> => ({
    name: 'experiment-saved-metrics-retrieve',
    schema: ExperimentSavedMetricsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof ExperimentSavedMetricsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ExperimentSavedMetric>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/experiment_saved_metrics/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const ExperimentShipVariantSchema = ExperimentsShipVariantCreateParams.omit({ project_id: true })
    .extend(ExperimentsShipVariantCreateBody.shape)
    .extend({ id: z.preprocess(castStringToInt, ExperimentsShipVariantCreateParams.shape['id']) })

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
            if (params.open_cleanup_pr !== undefined) {
                body['open_cleanup_pr'] = params.open_cleanup_pr
            }
            if (params.variant_key !== undefined) {
                body['variant_key'] = params.variant_key
            }
            if (params.release_to_everyone !== undefined) {
                body['release_to_everyone'] = params.release_to_everyone
            }
            const result = await context.api.request<Schemas.Experiment>({
                method: 'POST',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/${encodeURIComponent(String(params.id))}/ship_variant/`,
                body,
            })
            return await withPostHogUrl(context, result, `/experiments/${result.id}`)
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

const ExperimentTimeseriesResultsSchema = ExperimentsTimeseriesResultsRetrieveParams.omit({ project_id: true })
    .extend(ExperimentsTimeseriesResultsRetrieveQueryParams.shape)
    .extend({ id: z.preprocess(castStringToInt, ExperimentsTimeseriesResultsRetrieveParams.shape['id']) })

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

const ExperimentUnarchiveSchema = ExperimentsUnarchiveCreateParams.omit({ project_id: true }).extend({
    id: z.preprocess(castStringToInt, ExperimentsUnarchiveCreateParams.shape['id']),
})

const experimentUnarchive = (): ToolBase<typeof ExperimentUnarchiveSchema, WithPostHogUrl<Schemas.Experiment>> =>
    withUiApp('experiment', {
        name: 'experiment-unarchive',
        schema: ExperimentUnarchiveSchema,
        handler: async (context: Context, params: z.infer<typeof ExperimentUnarchiveSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.Experiment>({
                method: 'POST',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/experiments/${encodeURIComponent(String(params.id))}/unarchive/`,
            })
            return await withPostHogUrl(context, result, `/experiments/${result.id}`)
        },
    })

const ExperimentUpdateSchema = ExperimentsPartialUpdateParams.omit({ project_id: true })
    .extend(
        ExperimentsPartialUpdateBody.omit({
            start_date: true,
            end_date: true,
            feature_flag_key: true,
            secondary_metrics: true,
            filters: true,
            deleted: true,
            type: true,
            scheduling_config: true,
            _create_in_folder: true,
            primary_metrics_ordered_uuids: true,
            secondary_metrics_ordered_uuids: true,
            only_count_matured_users: true,
        }).shape
    )
    .extend({
        id: z.preprocess(castStringToInt, ExperimentsPartialUpdateParams.shape['id']),
        feature_flag: ExperimentsPartialUpdateBody.shape['feature_flag'].describe(
            'Variant split, rollout scope, payloads, and experience continuity for the linked feature flag, in the flag\'s own filters shape. This is the canonical input, do not send flag config via the deprecated parameters keys (feature_flag_variants, rollout_percentage). Set filters.multivariate.variants (each with key and rollout_percentage; percentages must sum to 100, exactly one key must be the literal string \'control\') to change the variant split. Set filters.groups to a single group [{"properties": [], "rollout_percentage": N}] (0-100) to change the overall rollout. Config this object omits is preserved from the flag\'s current state. On a running experiment this requires update_feature_flag_params=true (see rule 1: warn the user first).'
        ),
        running_time_calculation: ExperimentsPartialUpdateBody.shape['running_time_calculation'].describe(
            "Persist a running-time / sample-size plan onto the experiment (the planning target shown in the experiment's running-time panel). Object with optional keys: minimum_detectable_effect (percentage, e.g. 20 for a 20% lift), recommended_sample_size (total across all variants), recommended_running_time (days), and exposure_estimate_config."
        ),
        saved_metrics_ids: SavedMetricsAttachSchema.optional(),
    })

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
            if (params.feature_flag !== undefined) {
                body['feature_flag'] = params.feature_flag
            }
            if (params.holdout_id !== undefined) {
                body['holdout_id'] = params.holdout_id
            }
            if (params.parameters !== undefined) {
                body['parameters'] = params.parameters
            }
            if (params.running_time_calculation !== undefined) {
                body['running_time_calculation'] = params.running_time_calculation
            }
            if (params.excluded_variants !== undefined) {
                body['excluded_variants'] = params.excluded_variants
            }
            if (params.saved_metrics_ids !== undefined) {
                body['saved_metrics_ids'] = params.saved_metrics_ids
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
            const filtered = pickResponseFields(result, [
                'id',
                'name',
                'description',
                'type',
                'feature_flag_key',
                'status',
                'archived',
                'start_date',
                'end_date',
                'created_at',
                'parameters',
                'running_time_calculation',
                'metrics',
                'metrics_secondary',
                'saved_metrics',
                'conclusion',
                'conclusion_comment',
            ]) as typeof result
            return await withPostHogUrl(context, filtered, `/experiments/${filtered.id}`)
        },
    })

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'experiment-archive': experimentArchive,
    'experiment-calculate-running-time': experimentCalculateRunningTime,
    'experiment-copy-to-project': experimentCopyToProject,
    'experiment-create': experimentCreate,
    'experiment-delete': experimentDelete,
    'experiment-duplicate': experimentDuplicate,
    'experiment-end': experimentEnd,
    'experiment-get': experimentGet,
    'experiment-holdouts-create': experimentHoldoutsCreate,
    'experiment-holdouts-destroy': experimentHoldoutsDestroy,
    'experiment-holdouts-list': experimentHoldoutsList,
    'experiment-holdouts-partial-update': experimentHoldoutsPartialUpdate,
    'experiment-holdouts-retrieve': experimentHoldoutsRetrieve,
    'experiment-launch': experimentLaunch,
    'experiment-list': experimentList,
    'experiment-pause': experimentPause,
    'experiment-reset': experimentReset,
    'experiment-resume': experimentResume,
    'experiment-saved-metrics-create': experimentSavedMetricsCreate,
    'experiment-saved-metrics-destroy': experimentSavedMetricsDestroy,
    'experiment-saved-metrics-list': experimentSavedMetricsList,
    'experiment-saved-metrics-partial-update': experimentSavedMetricsPartialUpdate,
    'experiment-saved-metrics-retrieve': experimentSavedMetricsRetrieve,
    'experiment-ship-variant': experimentShipVariant,
    'experiment-stats': experimentStats,
    'experiment-timeseries-results': experimentTimeseriesResults,
    'experiment-unarchive': experimentUnarchive,
    'experiment-update': experimentUpdate,
}
