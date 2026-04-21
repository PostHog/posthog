// AUTO-GENERATED from products/early_access_features/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    EarlyAccessFeatureCreateBody,
    EarlyAccessFeatureDestroyParams,
    EarlyAccessFeatureListQueryParams,
    EarlyAccessFeaturePartialUpdateBody,
    EarlyAccessFeaturePartialUpdateParams,
    EarlyAccessFeatureRetrieveParams,
} from '@/generated/early_access_features/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const EarlyAccessFeatureListSchema = EarlyAccessFeatureListQueryParams

const earlyAccessFeatureList = (): ToolBase<
    typeof EarlyAccessFeatureListSchema,
    WithPostHogUrl<Schemas.PaginatedEarlyAccessFeatureList>
> => ({
    name: 'early-access-feature-list',
    schema: EarlyAccessFeatureListSchema,
    handler: async (context: Context, params: z.infer<typeof EarlyAccessFeatureListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedEarlyAccessFeatureList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/early_access_feature/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/early_access_features')
    },
})

const EarlyAccessFeatureCreateSchema = EarlyAccessFeatureCreateBody.omit({ _create_in_folder: true })

const earlyAccessFeatureCreate = (): ToolBase<
    typeof EarlyAccessFeatureCreateSchema,
    WithPostHogUrl<Schemas.EarlyAccessFeatureSerializerCreateOnly>
> => ({
    name: 'early-access-feature-create',
    schema: EarlyAccessFeatureCreateSchema,
    handler: async (context: Context, params: z.infer<typeof EarlyAccessFeatureCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.stage !== undefined) {
            body['stage'] = params.stage
        }
        if (params.documentation_url !== undefined) {
            body['documentation_url'] = params.documentation_url
        }
        if (params.payload !== undefined) {
            body['payload'] = params.payload
        }
        if (params.feature_flag_id !== undefined) {
            body['feature_flag_id'] = params.feature_flag_id
        }
        const result = await context.api.request<Schemas.EarlyAccessFeatureSerializerCreateOnly>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/early_access_feature/`,
            body,
        })
        return await withPostHogUrl(context, result, `/early_access_features/${result.id}`)
    },
})

const EarlyAccessFeatureRetrieveSchema = EarlyAccessFeatureRetrieveParams.omit({ project_id: true })

const earlyAccessFeatureRetrieve = (): ToolBase<
    typeof EarlyAccessFeatureRetrieveSchema,
    WithPostHogUrl<Schemas.EarlyAccessFeature>
> => ({
    name: 'early-access-feature-retrieve',
    schema: EarlyAccessFeatureRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof EarlyAccessFeatureRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.EarlyAccessFeature>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/early_access_feature/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/early_access_features/${result.id}`)
    },
})

const EarlyAccessFeaturePartialUpdateSchema = EarlyAccessFeaturePartialUpdateParams.omit({ project_id: true }).extend(
    EarlyAccessFeaturePartialUpdateBody.shape
)

const earlyAccessFeaturePartialUpdate = (): ToolBase<
    typeof EarlyAccessFeaturePartialUpdateSchema,
    WithPostHogUrl<Schemas.EarlyAccessFeature>
> => ({
    name: 'early-access-feature-partial-update',
    schema: EarlyAccessFeaturePartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof EarlyAccessFeaturePartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.stage !== undefined) {
            body['stage'] = params.stage
        }
        if (params.documentation_url !== undefined) {
            body['documentation_url'] = params.documentation_url
        }
        const result = await context.api.request<Schemas.EarlyAccessFeature>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/early_access_feature/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/early_access_features/${result.id}`)
    },
})

const EarlyAccessFeatureDestroySchema = EarlyAccessFeatureDestroyParams.omit({ project_id: true })

const earlyAccessFeatureDestroy = (): ToolBase<typeof EarlyAccessFeatureDestroySchema, unknown> => ({
    name: 'early-access-feature-destroy',
    schema: EarlyAccessFeatureDestroySchema,
    handler: async (context: Context, params: z.infer<typeof EarlyAccessFeatureDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/early_access_feature/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'early-access-feature-list': earlyAccessFeatureList,
    'early-access-feature-create': earlyAccessFeatureCreate,
    'early-access-feature-retrieve': earlyAccessFeatureRetrieve,
    'early-access-feature-partial-update': earlyAccessFeaturePartialUpdate,
    'early-access-feature-destroy': earlyAccessFeatureDestroy,
}
