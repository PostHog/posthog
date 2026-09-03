// AUTO-GENERATED from products/feature_flags/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/feature_flags/api'
import { withUiApp } from '@/resources/ui-apps'
import { validateDistinctIdPersonIdExclusive } from '@/schema/tool-inputs'
import { castStringToInt } from '@/tools/cast-helpers'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const CreateFeatureFlagSchema = () => {
    const FeatureFlagsCreateBody = orvalSchemas.FeatureFlagsCreateBody()
    return FeatureFlagsCreateBody.omit({ archived: true }).extend({
        is_remote_configuration: FeatureFlagsCreateBody.shape['is_remote_configuration'].describe(
            'Whether this flag delivers a payload instead of gating a feature (Remote Config mode). When true, set the delivered payload through the `filters` param under `filters.payloads.true` as a JSON-encoded string. There is no dedicated payload parameter.'
        ),
        ensure_experience_continuity: FeatureFlagsCreateBody.shape['ensure_experience_continuity'].describe(
            'Whether to persist the flag\'s value for a user across the anonymous-to-identified transition (the "persist across authentication steps" option in the UI). Keeps a user\'s evaluated value stable once they log in. Incompatible with `device_id` bucketing.'
        ),
        evaluation_runtime: FeatureFlagsCreateBody.shape['evaluation_runtime'].describe(
            'Where this flag is allowed to evaluate — `server` (server-side SDKs only), `client` (client-side SDKs only), or `all` (both). Defaults to `all`.'
        ),
        bucketing_identifier: FeatureFlagsCreateBody.shape['bucketing_identifier'].describe(
            'Identifier used to bucket users into rollout percentages and variants — `distinct_id` (user ID, the default) or `device_id`. Using `device_id` is incompatible with `ensure_experience_continuity=true`.'
        ),
    })
}

const createFeatureFlag = (): ToolBase<
    ReturnType<typeof CreateFeatureFlagSchema>,
    WithPostHogUrl<Schemas.FeatureFlag>
> => ({
    name: 'create-feature-flag',
    schema: CreateFeatureFlagSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CreateFeatureFlagSchema>>) => {
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
        if (params.is_remote_configuration !== undefined) {
            body['is_remote_configuration'] = params.is_remote_configuration
        }
        if (params.ensure_experience_continuity !== undefined) {
            body['ensure_experience_continuity'] = params.ensure_experience_continuity
        }
        if (params.evaluation_runtime !== undefined) {
            body['evaluation_runtime'] = params.evaluation_runtime
        }
        if (params.bucketing_identifier !== undefined) {
            body['bucketing_identifier'] = params.bucketing_identifier
        }
        const result = await context.api.request<Schemas.FeatureFlag>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/`,
            body,
        })
        return await withPostHogUrl(context, result, `/feature_flags/${result.id}`)
    },
})

const DeleteFeatureFlagSchema = () => {
    const FeatureFlagsDestroyParams = orvalSchemas.FeatureFlagsDestroyParams()
    return FeatureFlagsDestroyParams.omit({ project_id: true }).extend({
        id: z.preprocess(castStringToInt, FeatureFlagsDestroyParams.shape['id']),
    })
}

const deleteFeatureFlag = (): ToolBase<ReturnType<typeof DeleteFeatureFlagSchema>, Schemas.FeatureFlag> => ({
    name: 'delete-feature-flag',
    schema: DeleteFeatureFlagSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof DeleteFeatureFlagSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.FeatureFlag>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/`,
            body: { deleted: true },
        })
        return result
    },
})

const FeatureFlagArchiveSchema = () => {
    const FeatureFlagsArchiveCreateParams = orvalSchemas.FeatureFlagsArchiveCreateParams()
    return FeatureFlagsArchiveCreateParams.omit({ project_id: true }).extend({
        id: z.preprocess(castStringToInt, FeatureFlagsArchiveCreateParams.shape['id']),
    })
}

const featureFlagArchive = (): ToolBase<
    ReturnType<typeof FeatureFlagArchiveSchema>,
    WithPostHogUrl<Schemas.FeatureFlag>
> => ({
    name: 'feature-flag-archive',
    schema: FeatureFlagArchiveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof FeatureFlagArchiveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.FeatureFlag>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/archive/`,
        })
        const filtered = pickResponseFields(result, [
            'id',
            'key',
            'active',
            'archived',
            'status',
            'version',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/feature_flags/${filtered.id}`)
    },
})

const FeatureFlagDisableSchema = () => {
    const FeatureFlagsDisableCreateParams = orvalSchemas.FeatureFlagsDisableCreateParams()
    return FeatureFlagsDisableCreateParams.omit({ project_id: true }).extend({
        id: z.preprocess(castStringToInt, FeatureFlagsDisableCreateParams.shape['id']),
    })
}

const featureFlagDisable = (): ToolBase<
    ReturnType<typeof FeatureFlagDisableSchema>,
    WithPostHogUrl<Schemas.FeatureFlag>
> => ({
    name: 'feature-flag-disable',
    schema: FeatureFlagDisableSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof FeatureFlagDisableSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.FeatureFlag>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/disable/`,
        })
        const filtered = pickResponseFields(result, [
            'id',
            'key',
            'active',
            'archived',
            'status',
            'version',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/feature_flags/${filtered.id}`)
    },
})

const FeatureFlagEnableSchema = () => {
    const FeatureFlagsEnableCreateParams = orvalSchemas.FeatureFlagsEnableCreateParams()
    return FeatureFlagsEnableCreateParams.omit({ project_id: true }).extend({
        id: z.preprocess(castStringToInt, FeatureFlagsEnableCreateParams.shape['id']),
    })
}

const featureFlagEnable = (): ToolBase<
    ReturnType<typeof FeatureFlagEnableSchema>,
    WithPostHogUrl<Schemas.FeatureFlag>
> => ({
    name: 'feature-flag-enable',
    schema: FeatureFlagEnableSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof FeatureFlagEnableSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.FeatureFlag>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/enable/`,
        })
        const filtered = pickResponseFields(result, [
            'id',
            'key',
            'active',
            'archived',
            'status',
            'version',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/feature_flags/${filtered.id}`)
    },
})

const FeatureFlagGetAllSchema = () => {
    const FeatureFlagsListQueryParams = orvalSchemas.FeatureFlagsListQueryParams()
    return FeatureFlagsListQueryParams.extend({
        search: FeatureFlagsListQueryParams.shape['search'].describe(
            'Search by feature flag key or name (case-insensitive). Use this to find the flag ID for get/update/delete tools.'
        ),
        limit: z.preprocess(castStringToInt, FeatureFlagsListQueryParams.shape['limit']).optional(),
        offset: z.preprocess(castStringToInt, FeatureFlagsListQueryParams.shape['offset']).optional(),
    })
}

const featureFlagGetAll = (): ToolBase<
    ReturnType<typeof FeatureFlagGetAllSchema>,
    WithPostHogUrl<Schemas.PaginatedFeatureFlagList>
> => ({
    name: 'feature-flag-get-all',
    schema: FeatureFlagGetAllSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof FeatureFlagGetAllSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedFeatureFlagList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/`,
            query: {
                active: params.active,
                archived: params.archived,
                created_by_id: params.created_by_id,
                eligible_for_experiment: params.eligible_for_experiment,
                evaluation_runtime: params.evaluation_runtime,
                excluded_properties: params.excluded_properties,
                excluded_tags: params.excluded_tags,
                has_evaluation_contexts: params.has_evaluation_contexts,
                key: params.key,
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

const FeatureFlagGetDefinitionSchema = () => {
    const FeatureFlagsRetrieveParams = orvalSchemas.FeatureFlagsRetrieveParams()
    return FeatureFlagsRetrieveParams.omit({ project_id: true }).extend({
        id: z.preprocess(castStringToInt, FeatureFlagsRetrieveParams.shape['id']),
    })
}

const featureFlagGetDefinition = (): ToolBase<
    ReturnType<typeof FeatureFlagGetDefinitionSchema>,
    WithPostHogUrl<Schemas.FeatureFlag>
> => ({
    name: 'feature-flag-get-definition',
    schema: FeatureFlagGetDefinitionSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof FeatureFlagGetDefinitionSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.FeatureFlag>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/feature_flags/${result.id}`)
    },
})

const FeatureFlagUnarchiveSchema = () => {
    const FeatureFlagsUnarchiveCreateParams = orvalSchemas.FeatureFlagsUnarchiveCreateParams()
    return FeatureFlagsUnarchiveCreateParams.omit({ project_id: true }).extend({
        id: z.preprocess(castStringToInt, FeatureFlagsUnarchiveCreateParams.shape['id']),
    })
}

const featureFlagUnarchive = (): ToolBase<
    ReturnType<typeof FeatureFlagUnarchiveSchema>,
    WithPostHogUrl<Schemas.FeatureFlag>
> => ({
    name: 'feature-flag-unarchive',
    schema: FeatureFlagUnarchiveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof FeatureFlagUnarchiveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.FeatureFlag>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/unarchive/`,
        })
        const filtered = pickResponseFields(result, [
            'id',
            'key',
            'active',
            'archived',
            'status',
            'version',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/feature_flags/${filtered.id}`)
    },
})

const FeatureFlagsActivityRetrieveSchema = () => {
    const FeatureFlagsActivityRetrieveParams = orvalSchemas.FeatureFlagsActivityRetrieveParams()
    const FeatureFlagsActivityRetrieveQueryParams = orvalSchemas.FeatureFlagsActivityRetrieveQueryParams()
    return FeatureFlagsActivityRetrieveParams.omit({ project_id: true })
        .extend(FeatureFlagsActivityRetrieveQueryParams.shape)
        .extend({ id: z.preprocess(castStringToInt, FeatureFlagsActivityRetrieveParams.shape['id']) })
}

const featureFlagsActivityRetrieve = (): ToolBase<
    ReturnType<typeof FeatureFlagsActivityRetrieveSchema>,
    Schemas.ActivityLogPaginatedResponse
> => ({
    name: 'feature-flags-activity-retrieve',
    schema: FeatureFlagsActivityRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof FeatureFlagsActivityRetrieveSchema>>) => {
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

const FeatureFlagsBulkDeleteCreateSchema = () => {
    const FeatureFlagsBulkDeleteCreateBody = orvalSchemas.FeatureFlagsBulkDeleteCreateBody()
    return FeatureFlagsBulkDeleteCreateBody
}

const featureFlagsBulkDeleteCreate = (): ToolBase<
    ReturnType<typeof FeatureFlagsBulkDeleteCreateSchema>,
    Schemas.BulkDeleteResponse
> => ({
    name: 'feature-flags-bulk-delete-create',
    schema: FeatureFlagsBulkDeleteCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof FeatureFlagsBulkDeleteCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.ids !== undefined) {
            body['ids'] = params.ids
        }
        const result = await context.api.request<Schemas.BulkDeleteResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/bulk_delete/`,
            body,
        })
        return result
    },
})

const FeatureFlagsBulkKeysRetrieveSchema = () => {
    const FeatureFlagsBulkKeysRetrieveBody = orvalSchemas.FeatureFlagsBulkKeysRetrieveBody()
    return FeatureFlagsBulkKeysRetrieveBody
}

const featureFlagsBulkKeysRetrieve = (): ToolBase<
    ReturnType<typeof FeatureFlagsBulkKeysRetrieveSchema>,
    Schemas.BulkKeysResponse
> => ({
    name: 'feature-flags-bulk-keys-retrieve',
    schema: FeatureFlagsBulkKeysRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof FeatureFlagsBulkKeysRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.ids !== undefined) {
            body['ids'] = params.ids
        }
        const result = await context.api.request<Schemas.BulkKeysResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/bulk_keys/`,
            body,
        })
        return result
    },
})

const FeatureFlagsBulkUpdateTagsCreateSchema = () => {
    const FeatureFlagsBulkUpdateTagsCreateBody = orvalSchemas.FeatureFlagsBulkUpdateTagsCreateBody()
    return FeatureFlagsBulkUpdateTagsCreateBody
}

const featureFlagsBulkUpdateTagsCreate = (): ToolBase<
    ReturnType<typeof FeatureFlagsBulkUpdateTagsCreateSchema>,
    Schemas.BulkUpdateTagsResponse
> => ({
    name: 'feature-flags-bulk-update-tags-create',
    schema: FeatureFlagsBulkUpdateTagsCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof FeatureFlagsBulkUpdateTagsCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.ids !== undefined) {
            body['ids'] = params.ids
        }
        if (params.action !== undefined) {
            body['action'] = params.action
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        const result = await context.api.request<Schemas.BulkUpdateTagsResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/bulk_update_tags/`,
            body,
        })
        return result
    },
})

const FeatureFlagsCopyDependenciesCheckSchema = () => {
    const FeatureFlagsCopyFlagsDependencyRequirementsCreateBody =
        orvalSchemas.FeatureFlagsCopyFlagsDependencyRequirementsCreateBody()
    return FeatureFlagsCopyFlagsDependencyRequirementsCreateBody
}

const featureFlagsCopyDependenciesCheck = (): ToolBase<
    ReturnType<typeof FeatureFlagsCopyDependenciesCheckSchema>,
    Schemas.CopyFlagsDependencyRequirementsResponse
> => ({
    name: 'feature-flags-copy-dependencies-check',
    schema: FeatureFlagsCopyDependenciesCheckSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof FeatureFlagsCopyDependenciesCheckSchema>>) => {
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
        const result = await context.api.request<Schemas.CopyFlagsDependencyRequirementsResponse>({
            method: 'POST',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/feature_flags/copy_flags/dependency_requirements/`,
            body,
        })
        return result
    },
})

const FeatureFlagsCopyFlagsCreateSchema = () => {
    const FeatureFlagsCopyFlagsCreateBody = orvalSchemas.FeatureFlagsCopyFlagsCreateBody()
    return FeatureFlagsCopyFlagsCreateBody
}

const featureFlagsCopyFlagsCreate = (): ToolBase<
    ReturnType<typeof FeatureFlagsCopyFlagsCreateSchema>,
    Schemas.CopyFlagsResponse
> => ({
    name: 'feature-flags-copy-flags-create',
    schema: FeatureFlagsCopyFlagsCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof FeatureFlagsCopyFlagsCreateSchema>>) => {
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
        if (params.copy_dependencies !== undefined) {
            body['copy_dependencies'] = params.copy_dependencies
        }
        const result = await context.api.request<Schemas.CopyFlagsResponse>({
            method: 'POST',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/feature_flags/copy_flags/`,
            body,
        })
        return result
    },
})

const FeatureFlagsDependentFlagsRetrieveSchema = () => {
    const FeatureFlagsDependentFlagsListParams = orvalSchemas.FeatureFlagsDependentFlagsListParams()
    return FeatureFlagsDependentFlagsListParams.omit({ project_id: true }).extend({
        id: z.preprocess(castStringToInt, FeatureFlagsDependentFlagsListParams.shape['id']),
    })
}

const featureFlagsDependentFlagsRetrieve = (): ToolBase<
    ReturnType<typeof FeatureFlagsDependentFlagsRetrieveSchema>,
    Schemas.DependentFlag[]
> => ({
    name: 'feature-flags-dependent-flags-retrieve',
    schema: FeatureFlagsDependentFlagsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof FeatureFlagsDependentFlagsRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DependentFlag[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/dependent_flags/`,
        })
        return result
    },
})

const FeatureFlagsEvaluationReasonsRetrieveSchema = () => {
    const FeatureFlagsEvaluationReasonsRetrieveQueryParams =
        orvalSchemas.FeatureFlagsEvaluationReasonsRetrieveQueryParams()
    return FeatureFlagsEvaluationReasonsRetrieveQueryParams
}

const featureFlagsEvaluationReasonsRetrieve = (): ToolBase<
    ReturnType<typeof FeatureFlagsEvaluationReasonsRetrieveSchema>,
    unknown
> => ({
    name: 'feature-flags-evaluation-reasons-retrieve',
    schema: FeatureFlagsEvaluationReasonsRetrieveSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof FeatureFlagsEvaluationReasonsRetrieveSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/evaluation_reasons/`,
            query: {
                distinct_id: params.distinct_id,
                flag_keys: params.flag_keys,
                groups: params.groups,
            },
        })
        return result
    },
})

const FeatureFlagsMyFlagsRetrieveSchema = () => {
    const FeatureFlagsMyFlagsRetrieveQueryParams = orvalSchemas.FeatureFlagsMyFlagsRetrieveQueryParams()
    return FeatureFlagsMyFlagsRetrieveQueryParams
}

const featureFlagsMyFlagsRetrieve = (): ToolBase<
    ReturnType<typeof FeatureFlagsMyFlagsRetrieveSchema>,
    WithPostHogUrl<Schemas.MyFlagsResponse[]>
> => ({
    name: 'feature-flags-my-flags-retrieve',
    schema: FeatureFlagsMyFlagsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof FeatureFlagsMyFlagsRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.MyFlagsResponse[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/my_flags/`,
            query: {
                flag_keys: params.flag_keys,
                groups: params.groups,
            },
        })
        return await withPostHogUrl(context, result, '/feature_flags')
    },
})

const FeatureFlagsStatusRetrieveSchema = () => {
    const FeatureFlagsStatusRetrieveParams = orvalSchemas.FeatureFlagsStatusRetrieveParams()
    return FeatureFlagsStatusRetrieveParams.omit({ project_id: true }).extend({
        id: z.preprocess(castStringToInt, FeatureFlagsStatusRetrieveParams.shape['id']),
    })
}

const featureFlagsStatusRetrieve = (): ToolBase<
    ReturnType<typeof FeatureFlagsStatusRetrieveSchema>,
    Schemas.FeatureFlagStatusResponse
> => ({
    name: 'feature-flags-status-retrieve',
    schema: FeatureFlagsStatusRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof FeatureFlagsStatusRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.FeatureFlagStatusResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/status/`,
        })
        return result
    },
})

const FeatureFlagsTestEvaluationCreateSchema = () => {
    const FeatureFlagsTestEvaluationCreateBody = orvalSchemas.FeatureFlagsTestEvaluationCreateBody()
    const FeatureFlagsTestEvaluationCreateParams = orvalSchemas.FeatureFlagsTestEvaluationCreateParams()
    return FeatureFlagsTestEvaluationCreateParams.omit({ project_id: true })
        .extend(FeatureFlagsTestEvaluationCreateBody.shape)
        .extend({ id: z.preprocess(castStringToInt, FeatureFlagsTestEvaluationCreateParams.shape['id']) })
        .superRefine(validateDistinctIdPersonIdExclusive)
}

const featureFlagsTestEvaluationCreate = (): ToolBase<
    ReturnType<typeof FeatureFlagsTestEvaluationCreateSchema>,
    Schemas.FeatureFlagTestEvaluationResponse
> =>
    withUiApp('feature-flag-testing', {
        name: 'feature-flags-test-evaluation-create',
        schema: FeatureFlagsTestEvaluationCreateSchema(),
        handler: async (
            context: Context,
            params: z.infer<ReturnType<typeof FeatureFlagsTestEvaluationCreateSchema>>
        ) => {
            const projectId = await context.stateManager.getProjectId()
            const body: Record<string, unknown> = {}
            if (params.distinct_id !== undefined) {
                body['distinct_id'] = params.distinct_id
            }
            if (params.person_id !== undefined) {
                body['person_id'] = params.person_id
            }
            if (params.timestamp !== undefined) {
                body['timestamp'] = params.timestamp
            }
            if (params.groups !== undefined) {
                body['groups'] = params.groups
            }
            const result = await context.api.request<Schemas.FeatureFlagTestEvaluationResponse>({
                method: 'POST',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/test_evaluation/`,
                body,
            })
            return result
        },
    })

const FeatureFlagsUserBlastRadiusCreateSchema = () => {
    const FeatureFlagsUserBlastRadiusCreateBody = orvalSchemas.FeatureFlagsUserBlastRadiusCreateBody()
    return FeatureFlagsUserBlastRadiusCreateBody
}

const featureFlagsUserBlastRadiusCreate = (): ToolBase<
    ReturnType<typeof FeatureFlagsUserBlastRadiusCreateSchema>,
    Schemas.UserBlastRadiusResponse
> => ({
    name: 'feature-flags-user-blast-radius-create',
    schema: FeatureFlagsUserBlastRadiusCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof FeatureFlagsUserBlastRadiusCreateSchema>>) => {
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

const FeatureFlagsVersionsRetrieveSchema = () => {
    const FeatureFlagsVersionsRetrieveParams = orvalSchemas.FeatureFlagsVersionsRetrieveParams()
    return FeatureFlagsVersionsRetrieveParams.omit({ project_id: true }).extend({
        id: z.preprocess(
            castStringToInt,
            FeatureFlagsVersionsRetrieveParams.shape['id'].describe(
                'Numeric ID of the feature flag to reconstruct. Not the string key used in code.'
            )
        ),
        version_number: z.preprocess(
            castStringToInt,
            FeatureFlagsVersionsRetrieveParams.shape['version_number'].describe(
                "Version to reconstruct, counting up from 1. The flag's current `version` field is the highest available; asking for it returns the live definition with `is_historical` false."
            )
        ),
    })
}

const featureFlagsVersionsRetrieve = (): ToolBase<
    ReturnType<typeof FeatureFlagsVersionsRetrieveSchema>,
    Schemas.FeatureFlagVersionResponse
> => ({
    name: 'feature-flags-versions-retrieve',
    schema: FeatureFlagsVersionsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof FeatureFlagsVersionsRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.FeatureFlagVersionResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/versions/${encodeURIComponent(String(params.version_number))}/`,
        })
        return result
    },
})

const ScheduledChangesCreateSchema = () => {
    const ScheduledChangesCreateBody = orvalSchemas.ScheduledChangesCreateBody()
    return ScheduledChangesCreateBody
}

const scheduledChangesCreate = (): ToolBase<
    ReturnType<typeof ScheduledChangesCreateSchema>,
    Schemas.ScheduledChange
> => ({
    name: 'scheduled-changes-create',
    schema: ScheduledChangesCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ScheduledChangesCreateSchema>>) => {
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

const ScheduledChangesDeleteSchema = () => {
    const ScheduledChangesDestroyParams = orvalSchemas.ScheduledChangesDestroyParams()
    return ScheduledChangesDestroyParams.omit({ project_id: true })
}

const scheduledChangesDelete = (): ToolBase<ReturnType<typeof ScheduledChangesDeleteSchema>, unknown> => ({
    name: 'scheduled-changes-delete',
    schema: ScheduledChangesDeleteSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ScheduledChangesDeleteSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/scheduled_changes/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const ScheduledChangesGetSchema = () => {
    const ScheduledChangesRetrieveParams = orvalSchemas.ScheduledChangesRetrieveParams()
    return ScheduledChangesRetrieveParams.omit({ project_id: true })
}

const scheduledChangesGet = (): ToolBase<ReturnType<typeof ScheduledChangesGetSchema>, Schemas.ScheduledChange> => ({
    name: 'scheduled-changes-get',
    schema: ScheduledChangesGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ScheduledChangesGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ScheduledChange>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/scheduled_changes/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const ScheduledChangesListSchema = () => {
    const ScheduledChangesListQueryParams = orvalSchemas.ScheduledChangesListQueryParams()
    return ScheduledChangesListQueryParams.extend({
        model_name: ScheduledChangesListQueryParams.shape['model_name'].describe(
            'Filter by model type. Use "FeatureFlag" to see feature flag schedules.'
        ),
        record_id: ScheduledChangesListQueryParams.shape['record_id'].describe(
            'Filter by the ID of a specific feature flag.'
        ),
    })
}

const scheduledChangesList = (): ToolBase<
    ReturnType<typeof ScheduledChangesListSchema>,
    WithPostHogUrl<Schemas.PaginatedScheduledChangeList>
> => ({
    name: 'scheduled-changes-list',
    schema: ScheduledChangesListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ScheduledChangesListSchema>>) => {
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

const ScheduledChangesUpdateSchema = () => {
    const ScheduledChangesPartialUpdateBody = orvalSchemas.ScheduledChangesPartialUpdateBody()
    const ScheduledChangesPartialUpdateParams = orvalSchemas.ScheduledChangesPartialUpdateParams()
    return ScheduledChangesPartialUpdateParams.omit({ project_id: true }).extend(
        ScheduledChangesPartialUpdateBody.shape
    )
}

const scheduledChangesUpdate = (): ToolBase<
    ReturnType<typeof ScheduledChangesUpdateSchema>,
    Schemas.ScheduledChange
> => ({
    name: 'scheduled-changes-update',
    schema: ScheduledChangesUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ScheduledChangesUpdateSchema>>) => {
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

const UpdateFeatureFlagSchema = () => {
    const FeatureFlagsPartialUpdateBody = orvalSchemas.FeatureFlagsPartialUpdateBody()
    const FeatureFlagsPartialUpdateParams = orvalSchemas.FeatureFlagsPartialUpdateParams()
    return FeatureFlagsPartialUpdateParams.omit({ project_id: true })
        .extend(FeatureFlagsPartialUpdateBody.shape)
        .extend({
            id: z.preprocess(castStringToInt, FeatureFlagsPartialUpdateParams.shape['id']),
            is_remote_configuration: FeatureFlagsPartialUpdateBody.shape['is_remote_configuration'].describe(
                'Whether this flag delivers a payload instead of gating a feature (Remote Config mode). When true, set the delivered payload through the `filters` param under `filters.payloads.true` as a JSON-encoded string. There is no dedicated payload parameter.'
            ),
            ensure_experience_continuity: FeatureFlagsPartialUpdateBody.shape['ensure_experience_continuity'].describe(
                'Whether to persist the flag\'s value for a user across the anonymous-to-identified transition (the "persist across authentication steps" option in the UI). Keeps a user\'s evaluated value stable once they log in. Incompatible with `device_id` bucketing.'
            ),
            evaluation_runtime: FeatureFlagsPartialUpdateBody.shape['evaluation_runtime'].describe(
                'Where this flag is allowed to evaluate — `server` (server-side SDKs only), `client` (client-side SDKs only), or `all` (both). Defaults to `all`.'
            ),
            bucketing_identifier: FeatureFlagsPartialUpdateBody.shape['bucketing_identifier'].describe(
                'Identifier used to bucket users into rollout percentages and variants — `distinct_id` (user ID, the default) or `device_id`. Using `device_id` is incompatible with `ensure_experience_continuity=true`.'
            ),
        })
}

const updateFeatureFlag = (): ToolBase<
    ReturnType<typeof UpdateFeatureFlagSchema>,
    WithPostHogUrl<Schemas.FeatureFlag>
> => ({
    name: 'update-feature-flag',
    schema: UpdateFeatureFlagSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof UpdateFeatureFlagSchema>>) => {
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
        if (params.archived !== undefined) {
            body['archived'] = params.archived
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.evaluation_contexts !== undefined) {
            body['evaluation_contexts'] = params.evaluation_contexts
        }
        if (params.is_remote_configuration !== undefined) {
            body['is_remote_configuration'] = params.is_remote_configuration
        }
        if (params.ensure_experience_continuity !== undefined) {
            body['ensure_experience_continuity'] = params.ensure_experience_continuity
        }
        if (params.evaluation_runtime !== undefined) {
            body['evaluation_runtime'] = params.evaluation_runtime
        }
        if (params.bucketing_identifier !== undefined) {
            body['bucketing_identifier'] = params.bucketing_identifier
        }
        const result = await context.api.request<Schemas.FeatureFlag>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/feature_flags/${result.id}`)
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'create-feature-flag': createFeatureFlag,
    'delete-feature-flag': deleteFeatureFlag,
    'feature-flag-archive': featureFlagArchive,
    'feature-flag-disable': featureFlagDisable,
    'feature-flag-enable': featureFlagEnable,
    'feature-flag-get-all': featureFlagGetAll,
    'feature-flag-get-definition': featureFlagGetDefinition,
    'feature-flag-unarchive': featureFlagUnarchive,
    'feature-flags-activity-retrieve': featureFlagsActivityRetrieve,
    'feature-flags-bulk-delete-create': featureFlagsBulkDeleteCreate,
    'feature-flags-bulk-keys-retrieve': featureFlagsBulkKeysRetrieve,
    'feature-flags-bulk-update-tags-create': featureFlagsBulkUpdateTagsCreate,
    'feature-flags-copy-dependencies-check': featureFlagsCopyDependenciesCheck,
    'feature-flags-copy-flags-create': featureFlagsCopyFlagsCreate,
    'feature-flags-dependent-flags-retrieve': featureFlagsDependentFlagsRetrieve,
    'feature-flags-evaluation-reasons-retrieve': featureFlagsEvaluationReasonsRetrieve,
    'feature-flags-my-flags-retrieve': featureFlagsMyFlagsRetrieve,
    'feature-flags-status-retrieve': featureFlagsStatusRetrieve,
    'feature-flags-test-evaluation-create': featureFlagsTestEvaluationCreate,
    'feature-flags-user-blast-radius-create': featureFlagsUserBlastRadiusCreate,
    'feature-flags-versions-retrieve': featureFlagsVersionsRetrieve,
    'scheduled-changes-create': scheduledChangesCreate,
    'scheduled-changes-delete': scheduledChangesDelete,
    'scheduled-changes-get': scheduledChangesGet,
    'scheduled-changes-list': scheduledChangesList,
    'scheduled-changes-update': scheduledChangesUpdate,
    'update-feature-flag': updateFeatureFlag,
}
