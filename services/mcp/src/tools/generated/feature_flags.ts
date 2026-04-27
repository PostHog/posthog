// AUTO-GENERATED from products/feature_flags/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    FeatureFlagsActivityRetrieveParams,
    FeatureFlagsActivityRetrieveQueryParams,
    FeatureFlagsCopyFlagsCreateBody,
    FeatureFlagsCreateBody,
    FeatureFlagsDependentFlagsListParams,
    FeatureFlagsDestroyParams,
    FeatureFlagsEvaluationReasonsRetrieveQueryParams,
    FeatureFlagsListQueryParams,
    FeatureFlagsPartialUpdateBody,
    FeatureFlagsPartialUpdateParams,
    FeatureFlagsRetrieveParams,
    FeatureFlagsStatusRetrieveParams,
    FeatureFlagsUserBlastRadiusCreateBody,
    ScheduledChangesCreateBody,
    ScheduledChangesDestroyParams,
    ScheduledChangesListQueryParams,
    ScheduledChangesPartialUpdateBody,
    ScheduledChangesPartialUpdateParams,
    ScheduledChangesRetrieveParams,
} from '@/generated/feature_flags/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const FeatureFlagGetAllSchema = FeatureFlagsListQueryParams.extend({
    search: FeatureFlagsListQueryParams.shape['search'].describe(
        'Search by feature flag key or name (case-insensitive). Use this to find the flag ID for get/update/delete tools.'
    ),
})

const featureFlagGetAll = (): ToolBase<
    typeof FeatureFlagGetAllSchema,
    WithPostHogUrl<Schemas.PaginatedFeatureFlagList>
> => ({
    name: 'feature-flag-get-all',
    schema: FeatureFlagGetAllSchema,
    handler: async (context: Context, params: z.infer<typeof FeatureFlagGetAllSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedFeatureFlagList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/`,
            query: {
                active: params.active,
                created_by_id: params.created_by_id,
                evaluation_runtime: params.evaluation_runtime,
                excluded_properties: params.excluded_properties,
                has_evaluation_contexts: params.has_evaluation_contexts,
                limit: params.limit,
                offset: params.offset,
                search: params.search,
                tags: params.tags,
                type: params.type,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, ['id', 'key', 'name', 'updated_at', 'status', 'tags'])
            ),
        } as typeof result
        return await withPostHogUrl(
            context,
            {
                ...filtered,
                results: await Promise.all(
                    (filtered.results ?? []).map((item) => withPostHogUrl(context, item, `/feature_flags/${item.id}`))
                ),
            },
            '/feature_flags'
        )
    },
})

const FeatureFlagGetDefinitionSchema = FeatureFlagsRetrieveParams.omit({ project_id: true })

const featureFlagGetDefinition = (): ToolBase<
    typeof FeatureFlagGetDefinitionSchema,
    WithPostHogUrl<Schemas.FeatureFlag>
> => ({
    name: 'feature-flag-get-definition',
    schema: FeatureFlagGetDefinitionSchema,
    handler: async (context: Context, params: z.infer<typeof FeatureFlagGetDefinitionSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.FeatureFlag>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/feature_flags/${result.id}`)
    },
})

const CreateFeatureFlagSchema = FeatureFlagsCreateBody

const createFeatureFlag = (): ToolBase<typeof CreateFeatureFlagSchema, WithPostHogUrl<Schemas.FeatureFlag>> => ({
    name: 'create-feature-flag',
    schema: CreateFeatureFlagSchema,
    handler: async (context: Context, params: z.infer<typeof CreateFeatureFlagSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.key !== undefined) {
            body['key'] = params.key
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.active !== undefined) {
            body['active'] = params.active
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.evaluation_contexts !== undefined) {
            body['evaluation_contexts'] = params.evaluation_contexts
        }
        const result = await context.api.request<Schemas.FeatureFlag>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/`,
            body,
        })
        return await withPostHogUrl(context, result, `/feature_flags/${result.id}`)
    },
})

const UpdateFeatureFlagSchema = FeatureFlagsPartialUpdateParams.omit({ project_id: true }).extend(
    FeatureFlagsPartialUpdateBody.shape
)

const updateFeatureFlag = (): ToolBase<typeof UpdateFeatureFlagSchema, WithPostHogUrl<Schemas.FeatureFlag>> => ({
    name: 'update-feature-flag',
    schema: UpdateFeatureFlagSchema,
    handler: async (context: Context, params: z.infer<typeof UpdateFeatureFlagSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.key !== undefined) {
            body['key'] = params.key
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.active !== undefined) {
            body['active'] = params.active
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.evaluation_contexts !== undefined) {
            body['evaluation_contexts'] = params.evaluation_contexts
        }
        const result = await context.api.request<Schemas.FeatureFlag>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/feature_flags/${result.id}`)
    },
})

const DeleteFeatureFlagSchema = FeatureFlagsDestroyParams.omit({ project_id: true })

const deleteFeatureFlag = (): ToolBase<typeof DeleteFeatureFlagSchema, Schemas.FeatureFlag> => ({
    name: 'delete-feature-flag',
    schema: DeleteFeatureFlagSchema,
    handler: async (context: Context, params: z.infer<typeof DeleteFeatureFlagSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.FeatureFlag>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/`,
            body: { deleted: true },
        })
        return result
    },
})

const FeatureFlagsActivityRetrieveSchema = FeatureFlagsActivityRetrieveParams.omit({ project_id: true }).extend(
    FeatureFlagsActivityRetrieveQueryParams.shape
)

const featureFlagsActivityRetrieve = (): ToolBase<
    typeof FeatureFlagsActivityRetrieveSchema,
    Schemas.ActivityLogPaginatedResponse
> => ({
    name: 'feature-flags-activity-retrieve',
    schema: FeatureFlagsActivityRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof FeatureFlagsActivityRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ActivityLogPaginatedResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/activity/`,
            query: {
                limit: params.limit,
                page: params.page,
            },
        })
        return result
    },
})

const FeatureFlagsDependentFlagsRetrieveSchema = FeatureFlagsDependentFlagsListParams.omit({ project_id: true })

const featureFlagsDependentFlagsRetrieve = (): ToolBase<
    typeof FeatureFlagsDependentFlagsRetrieveSchema,
    Schemas.DependentFlag[]
> => ({
    name: 'feature-flags-dependent-flags-retrieve',
    schema: FeatureFlagsDependentFlagsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof FeatureFlagsDependentFlagsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DependentFlag[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/dependent_flags/`,
        })
        return result
    },
})

const FeatureFlagsStatusRetrieveSchema = FeatureFlagsStatusRetrieveParams.omit({ project_id: true })

const featureFlagsStatusRetrieve = (): ToolBase<
    typeof FeatureFlagsStatusRetrieveSchema,
    Schemas.FeatureFlagStatusResponse
> => ({
    name: 'feature-flags-status-retrieve',
    schema: FeatureFlagsStatusRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof FeatureFlagsStatusRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.FeatureFlagStatusResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/status/`,
        })
        return result
    },
})

const FeatureFlagsEvaluationReasonsRetrieveSchema = FeatureFlagsEvaluationReasonsRetrieveQueryParams

const featureFlagsEvaluationReasonsRetrieve = (): ToolBase<
    typeof FeatureFlagsEvaluationReasonsRetrieveSchema,
    unknown
> => ({
    name: 'feature-flags-evaluation-reasons-retrieve',
    schema: FeatureFlagsEvaluationReasonsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof FeatureFlagsEvaluationReasonsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/evaluation_reasons/`,
            query: {
                distinct_id: params.distinct_id,
                groups: params.groups,
            },
        })
        return result
    },
})

const FeatureFlagsUserBlastRadiusCreateSchema = FeatureFlagsUserBlastRadiusCreateBody

const featureFlagsUserBlastRadiusCreate = (): ToolBase<
    typeof FeatureFlagsUserBlastRadiusCreateSchema,
    Schemas.UserBlastRadiusResponse
> => ({
    name: 'feature-flags-user-blast-radius-create',
    schema: FeatureFlagsUserBlastRadiusCreateSchema,
    handler: async (context: Context, params: z.infer<typeof FeatureFlagsUserBlastRadiusCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.condition !== undefined) {
            body['condition'] = params.condition
        }
        if (params.group_type_index !== undefined) {
            body['group_type_index'] = params.group_type_index
        }
        const result = await context.api.request<Schemas.UserBlastRadiusResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/user_blast_radius/`,
            body,
        })
        return result
    },
})

const FeatureFlagsCopyFlagsCreateSchema = FeatureFlagsCopyFlagsCreateBody

const featureFlagsCopyFlagsCreate = (): ToolBase<
    typeof FeatureFlagsCopyFlagsCreateSchema,
    Schemas.CopyFlagsResponse
> => ({
    name: 'feature-flags-copy-flags-create',
    schema: FeatureFlagsCopyFlagsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof FeatureFlagsCopyFlagsCreateSchema>) => {
        const orgId = await context.stateManager.getOrgID()
        const body: Record<string, unknown> = {}
        if (params.feature_flag_key !== undefined) {
            body['feature_flag_key'] = params.feature_flag_key
        }
        if (params.from_project !== undefined) {
            body['from_project'] = params.from_project
        }
        if (params.target_project_ids !== undefined) {
            body['target_project_ids'] = params.target_project_ids
        }
        if (params.copy_schedule !== undefined) {
            body['copy_schedule'] = params.copy_schedule
        }
        if (params.disable_copied_flag !== undefined) {
            body['disable_copied_flag'] = params.disable_copied_flag
        }
        const result = await context.api.request<Schemas.CopyFlagsResponse>({
            method: 'POST',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/feature_flags/copy_flags/`,
            body,
        })
        return result
    },
})

const ScheduledChangesListSchema = ScheduledChangesListQueryParams.extend({
    model_name: ScheduledChangesListQueryParams.shape['model_name'].describe(
        'Filter by model type. Use "FeatureFlag" to see feature flag schedules.'
    ),
    record_id: ScheduledChangesListQueryParams.shape['record_id'].describe(
        'Filter by the ID of a specific feature flag.'
    ),
})

const scheduledChangesList = (): ToolBase<
    typeof ScheduledChangesListSchema,
    WithPostHogUrl<Schemas.PaginatedScheduledChangeList>
> => ({
    name: 'scheduled-changes-list',
    schema: ScheduledChangesListSchema,
    handler: async (context: Context, params: z.infer<typeof ScheduledChangesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedScheduledChangeList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/scheduled_changes/`,
            query: {
                limit: params.limit,
                model_name: params.model_name,
                offset: params.offset,
                record_id: params.record_id,
            },
        })
        return await withPostHogUrl(context, result, '/feature_flags')
    },
})

const ScheduledChangesGetSchema = ScheduledChangesRetrieveParams.omit({ project_id: true })

const scheduledChangesGet = (): ToolBase<typeof ScheduledChangesGetSchema, Schemas.ScheduledChange> => ({
    name: 'scheduled-changes-get',
    schema: ScheduledChangesGetSchema,
    handler: async (context: Context, params: z.infer<typeof ScheduledChangesGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ScheduledChange>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/scheduled_changes/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const ScheduledChangesCreateSchema = ScheduledChangesCreateBody

const scheduledChangesCreate = (): ToolBase<typeof ScheduledChangesCreateSchema, Schemas.ScheduledChange> => ({
    name: 'scheduled-changes-create',
    schema: ScheduledChangesCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ScheduledChangesCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.record_id !== undefined) {
            body['record_id'] = params.record_id
        }
        if (params.model_name !== undefined) {
            body['model_name'] = params.model_name
        }
        if (params.payload !== undefined) {
            body['payload'] = params.payload
        }
        if (params.scheduled_at !== undefined) {
            body['scheduled_at'] = params.scheduled_at
        }
        if (params.is_recurring !== undefined) {
            body['is_recurring'] = params.is_recurring
        }
        if (params.recurrence_interval !== undefined) {
            body['recurrence_interval'] = params.recurrence_interval
        }
        if (params.cron_expression !== undefined) {
            body['cron_expression'] = params.cron_expression
        }
        if (params.end_date !== undefined) {
            body['end_date'] = params.end_date
        }
        const result = await context.api.request<Schemas.ScheduledChange>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/scheduled_changes/`,
            body,
        })
        return result
    },
})

const ScheduledChangesUpdateSchema = ScheduledChangesPartialUpdateParams.omit({ project_id: true }).extend(
    ScheduledChangesPartialUpdateBody.shape
)

const scheduledChangesUpdate = (): ToolBase<typeof ScheduledChangesUpdateSchema, Schemas.ScheduledChange> => ({
    name: 'scheduled-changes-update',
    schema: ScheduledChangesUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof ScheduledChangesUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.record_id !== undefined) {
            body['record_id'] = params.record_id
        }
        if (params.model_name !== undefined) {
            body['model_name'] = params.model_name
        }
        if (params.payload !== undefined) {
            body['payload'] = params.payload
        }
        if (params.scheduled_at !== undefined) {
            body['scheduled_at'] = params.scheduled_at
        }
        if (params.is_recurring !== undefined) {
            body['is_recurring'] = params.is_recurring
        }
        if (params.recurrence_interval !== undefined) {
            body['recurrence_interval'] = params.recurrence_interval
        }
        if (params.cron_expression !== undefined) {
            body['cron_expression'] = params.cron_expression
        }
        if (params.end_date !== undefined) {
            body['end_date'] = params.end_date
        }
        const result = await context.api.request<Schemas.ScheduledChange>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/scheduled_changes/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const ScheduledChangesDeleteSchema = ScheduledChangesDestroyParams.omit({ project_id: true })

const scheduledChangesDelete = (): ToolBase<typeof ScheduledChangesDeleteSchema, unknown> => ({
    name: 'scheduled-changes-delete',
    schema: ScheduledChangesDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof ScheduledChangesDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/scheduled_changes/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'feature-flag-get-all': featureFlagGetAll,
    'feature-flag-get-definition': featureFlagGetDefinition,
    'create-feature-flag': createFeatureFlag,
    'update-feature-flag': updateFeatureFlag,
    'delete-feature-flag': deleteFeatureFlag,
    'feature-flags-activity-retrieve': featureFlagsActivityRetrieve,
    'feature-flags-dependent-flags-retrieve': featureFlagsDependentFlagsRetrieve,
    'feature-flags-status-retrieve': featureFlagsStatusRetrieve,
    'feature-flags-evaluation-reasons-retrieve': featureFlagsEvaluationReasonsRetrieve,
    'feature-flags-user-blast-radius-create': featureFlagsUserBlastRadiusCreate,
    'feature-flags-copy-flags-create': featureFlagsCopyFlagsCreate,
    'scheduled-changes-list': scheduledChangesList,
    'scheduled-changes-get': scheduledChangesGet,
    'scheduled-changes-create': scheduledChangesCreate,
    'scheduled-changes-update': scheduledChangesUpdate,
    'scheduled-changes-delete': scheduledChangesDelete,
}
