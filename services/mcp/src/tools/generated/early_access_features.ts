// AUTO-GENERATED from products/early_access_features/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/early_access_features/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const EarlyAccessFeatureCreateSchema = () => {
    const EarlyAccessFeatureCreateBody = orvalSchemas.EarlyAccessFeatureCreateBody()
    return EarlyAccessFeatureCreateBody.omit({ _create_in_folder: true })
}

const earlyAccessFeatureCreate = (): ToolBase<
    ReturnType<typeof EarlyAccessFeatureCreateSchema>,
    WithPostHogUrl<Schemas.EarlyAccessFeatureSerializerCreateOnly>
> => ({
    name: 'early-access-feature-create',
    schema: EarlyAccessFeatureCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof EarlyAccessFeatureCreateSchema>>) => {
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

const EarlyAccessFeatureDestroySchema = () => {
    const EarlyAccessFeatureDestroyParams = orvalSchemas.EarlyAccessFeatureDestroyParams()
    return EarlyAccessFeatureDestroyParams.omit({ project_id: true })
}

const earlyAccessFeatureDestroy = (): ToolBase<ReturnType<typeof EarlyAccessFeatureDestroySchema>, unknown> => ({
    name: 'early-access-feature-destroy',
    schema: EarlyAccessFeatureDestroySchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof EarlyAccessFeatureDestroySchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/early_access_feature/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const EarlyAccessFeatureListSchema = () => {
    const EarlyAccessFeatureListQueryParams = orvalSchemas.EarlyAccessFeatureListQueryParams()
    return EarlyAccessFeatureListQueryParams
}

const earlyAccessFeatureList = (): ToolBase<
    ReturnType<typeof EarlyAccessFeatureListSchema>,
    WithPostHogUrl<Schemas.PaginatedEarlyAccessFeatureList>
> => ({
    name: 'early-access-feature-list',
    schema: EarlyAccessFeatureListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof EarlyAccessFeatureListSchema>>) => {
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

const EarlyAccessFeaturePartialUpdateSchema = () => {
    const EarlyAccessFeaturePartialUpdateBody = orvalSchemas.EarlyAccessFeaturePartialUpdateBody()
    const EarlyAccessFeaturePartialUpdateParams = orvalSchemas.EarlyAccessFeaturePartialUpdateParams()
    return EarlyAccessFeaturePartialUpdateParams.omit({ project_id: true }).extend(
        EarlyAccessFeaturePartialUpdateBody.shape
    )
}

const earlyAccessFeaturePartialUpdate = (): ToolBase<
    ReturnType<typeof EarlyAccessFeaturePartialUpdateSchema>,
    WithPostHogUrl<Schemas.EarlyAccessFeature>
> => ({
    name: 'early-access-feature-partial-update',
    schema: EarlyAccessFeaturePartialUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof EarlyAccessFeaturePartialUpdateSchema>>) => {
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

const EarlyAccessFeatureRetrieveSchema = () => {
    const EarlyAccessFeatureRetrieveParams = orvalSchemas.EarlyAccessFeatureRetrieveParams()
    return EarlyAccessFeatureRetrieveParams.omit({ project_id: true })
}

const earlyAccessFeatureRetrieve = (): ToolBase<
    ReturnType<typeof EarlyAccessFeatureRetrieveSchema>,
    WithPostHogUrl<Schemas.EarlyAccessFeature>
> => ({
    name: 'early-access-feature-retrieve',
    schema: EarlyAccessFeatureRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof EarlyAccessFeatureRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.EarlyAccessFeature>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/early_access_feature/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/early_access_features/${result.id}`)
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'early-access-feature-create': earlyAccessFeatureCreate,
    'early-access-feature-destroy': earlyAccessFeatureDestroy,
    'early-access-feature-list': earlyAccessFeatureList,
    'early-access-feature-partial-update': earlyAccessFeaturePartialUpdate,
    'early-access-feature-retrieve': earlyAccessFeatureRetrieve,
}
