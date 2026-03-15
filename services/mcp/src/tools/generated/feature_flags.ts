// AUTO-GENERATED from products/feature_flags/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    FeatureFlagsCreateBody,
    FeatureFlagsDestroyParams,
    FeatureFlagsListQueryParams,
    FeatureFlagsPartialUpdateBody,
    FeatureFlagsPartialUpdateParams,
    FeatureFlagsRetrieve2Params,
} from '@/generated/feature_flags/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const FeatureFlagGetAllSchema = FeatureFlagsListQueryParams

const featureFlagGetAll = (): ToolBase<typeof FeatureFlagGetAllSchema, unknown> => ({
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
                has_evaluation_tags: params.has_evaluation_tags,
                limit: params.limit,
                offset: params.offset,
                search: params.search,
                tags: params.tags,
                type: params.type,
            },
        })
        const items = (result as any).results ?? result
        return {
            ...(result as any),
            results: (items as any[]).map((item: any) => ({
                ...item,
                _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/feature_flags/${item.id}`,
            })),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/feature_flags`,
        }
    },
})

const FeatureFlagGetDefinitionSchema = FeatureFlagsRetrieve2Params.omit({ project_id: true })

const featureFlagGetDefinition = (): ToolBase<
    typeof FeatureFlagGetDefinitionSchema,
    Schemas.FeatureFlag & { _posthogUrl: string }
> => ({
    name: 'feature-flag-get-definition',
    schema: FeatureFlagGetDefinitionSchema,
    handler: async (context: Context, params: z.infer<typeof FeatureFlagGetDefinitionSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.FeatureFlag>({
            method: 'GET',
            path: `/api/projects/${projectId}/feature_flags/${params.id}/`,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/feature_flags/${(result as any).id}`,
        }
    },
})

const CreateFeatureFlagSchema = FeatureFlagsCreateBody

const createFeatureFlag = (): ToolBase<
    typeof CreateFeatureFlagSchema,
    Schemas.FeatureFlag & { _posthogUrl: string }
> => ({
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
        if (params.evaluation_tags !== undefined) {
            body['evaluation_tags'] = params.evaluation_tags
        }
        const result = await context.api.request<Schemas.FeatureFlag>({
            method: 'POST',
            path: `/api/projects/${projectId}/feature_flags/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/feature_flags/${(result as any).id}`,
        }
    },
})

const UpdateFeatureFlagSchema = FeatureFlagsPartialUpdateParams.omit({ project_id: true }).extend(
    FeatureFlagsPartialUpdateBody.shape
)

const updateFeatureFlag = (): ToolBase<
    typeof UpdateFeatureFlagSchema,
    Schemas.FeatureFlag & { _posthogUrl: string }
> => ({
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
        if (params.evaluation_tags !== undefined) {
            body['evaluation_tags'] = params.evaluation_tags
        }
        const result = await context.api.request<Schemas.FeatureFlag>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/feature_flags/${params.id}/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/feature_flags/${(result as any).id}`,
        }
    },
})

const DeleteFeatureFlagSchema = FeatureFlagsDestroyParams.omit({ project_id: true })

const deleteFeatureFlag = (): ToolBase<typeof DeleteFeatureFlagSchema, unknown> => ({
    name: 'delete-feature-flag',
    schema: DeleteFeatureFlagSchema,
    handler: async (context: Context, params: z.infer<typeof DeleteFeatureFlagSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/feature_flags/${params.id}/`,
            body: { deleted: true },
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
}
