// AUTO-GENERATED from products/feature_flags/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    FeatureFlagsActivityRetrieve2Params,
    FeatureFlagsActivityRetrieve2QueryParams,
    FeatureFlagsCreateBody,
    FeatureFlagsDependentFlagsListParams,
    FeatureFlagsDestroyParams,
    FeatureFlagsEvaluationReasonsRetrieveQueryParams,
    FeatureFlagsListQueryParams,
    FeatureFlagsPartialUpdateBody,
    FeatureFlagsPartialUpdateParams,
    FeatureFlagsRetrieve2Params,
    FeatureFlagsStatusRetrieveParams,
    FeatureFlagsUserBlastRadiusCreateBody,
} from '@/generated/feature_flags/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const FeatureFlagGetAllSchema = FeatureFlagsListQueryParams

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
            path: `/api/projects/${projectId}/feature_flags/`,
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
            results: result.results.map((item: any) =>
                pickResponseFields(item, ['id', 'key', 'name', 'updated_at', 'status', 'tags'])
            ),
        } as typeof result
        return await withPostHogUrl(
            context,
            {
                ...filtered,
                results: await Promise.all(
                    filtered.results.map((item) => withPostHogUrl(context, item, `/feature_flags/${item.id}`))
                ),
            },
            '/feature_flags'
        )
    },
})

const FeatureFlagGetDefinitionSchema = FeatureFlagsRetrieve2Params.omit({ project_id: true })

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
            path: `/api/projects/${projectId}/feature_flags/${params.id}/`,
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
            path: `/api/projects/${projectId}/feature_flags/`,
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
            path: `/api/projects/${projectId}/feature_flags/${params.id}/`,
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
            path: `/api/projects/${projectId}/feature_flags/${params.id}/`,
            body: { deleted: true },
        })
        return result
    },
})

const FeatureFlagsActivityRetrieveSchema = FeatureFlagsActivityRetrieve2Params.omit({ project_id: true }).extend(
    FeatureFlagsActivityRetrieve2QueryParams.shape
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
            path: `/api/projects/${projectId}/feature_flags/${params.id}/activity/`,
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
            path: `/api/projects/${projectId}/feature_flags/${params.id}/dependent_flags/`,
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
            path: `/api/projects/${projectId}/feature_flags/${params.id}/status/`,
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
            path: `/api/projects/${projectId}/feature_flags/evaluation_reasons/`,
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
            path: `/api/projects/${projectId}/feature_flags/user_blast_radius/`,
            body,
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
}
