// AUTO-GENERATED from products/release/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/release/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ReleaseCreateSchema = () => {
    const ReleasesCreateBody = orvalSchemas.ReleasesCreateBody()
    return ReleasesCreateBody
}

const releaseCreate = (): ToolBase<ReturnType<typeof ReleaseCreateSchema>, WithPostHogUrl<Schemas.ReleaseDTO>> => ({
    name: 'release-create',
    schema: ReleaseCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ReleaseCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.owner_id !== undefined) {
            body['owner_id'] = params.owner_id
        }
        if (params.feature_flag_ids !== undefined) {
            body['feature_flag_ids'] = params.feature_flag_ids
        }
        if (params.broadcast_ids !== undefined) {
            body['broadcast_ids'] = params.broadcast_ids
        }
        if (params.survey_ids !== undefined) {
            body['survey_ids'] = params.survey_ids
        }
        if (params.insight_ids !== undefined) {
            body['insight_ids'] = params.insight_ids
        }
        if (params.metric_insight_ids !== undefined) {
            body['metric_insight_ids'] = params.metric_insight_ids
        }
        if (params.metric_goals !== undefined) {
            body['metric_goals'] = params.metric_goals
        }
        const result = await context.api.request<Schemas.ReleaseDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/releases/`,
            body,
        })
        return await withPostHogUrl(context, result, `/releases/${result.id}`)
    },
})

const ReleaseDeleteSchema = () => {
    const ReleasesDestroyParams = orvalSchemas.ReleasesDestroyParams()
    return ReleasesDestroyParams.omit({ project_id: true })
}

const releaseDelete = (): ToolBase<ReturnType<typeof ReleaseDeleteSchema>, unknown> => ({
    name: 'release-delete',
    schema: ReleaseDeleteSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ReleaseDeleteSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/releases/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const ReleaseGetSchema = () => {
    const ReleasesRetrieveParams = orvalSchemas.ReleasesRetrieveParams()
    return ReleasesRetrieveParams.omit({ project_id: true })
}

const releaseGet = (): ToolBase<ReturnType<typeof ReleaseGetSchema>, WithPostHogUrl<Schemas.ReleaseDTO>> => ({
    name: 'release-get',
    schema: ReleaseGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ReleaseGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReleaseDTO>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/releases/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/releases/${result.id}`)
    },
})

const ReleaseMergeSchema = () => {
    const ReleasesMergeCreateBody = orvalSchemas.ReleasesMergeCreateBody()
    const ReleasesMergeCreateParams = orvalSchemas.ReleasesMergeCreateParams()
    return ReleasesMergeCreateParams.omit({ project_id: true }).extend(ReleasesMergeCreateBody.shape)
}

const releaseMerge = (): ToolBase<ReturnType<typeof ReleaseMergeSchema>, WithPostHogUrl<Schemas.ReleaseDTO>> => ({
    name: 'release-merge',
    schema: ReleaseMergeSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ReleaseMergeSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.release_ids !== undefined) {
            body['release_ids'] = params.release_ids
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        const result = await context.api.request<Schemas.ReleaseDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/releases/${encodeURIComponent(String(params.id))}/merge/`,
            body,
        })
        return await withPostHogUrl(context, result, `/releases/${result.id}`)
    },
})

const ReleaseUpdateSchema = () => {
    const ReleasesPartialUpdateBody = orvalSchemas.ReleasesPartialUpdateBody()
    const ReleasesPartialUpdateParams = orvalSchemas.ReleasesPartialUpdateParams()
    return ReleasesPartialUpdateParams.omit({ project_id: true })
        .extend(ReleasesPartialUpdateBody.shape)
        .extend({
            feature_flag_ids: ReleasesPartialUpdateBody.shape['feature_flag_ids'].describe(
                'The full list of linked feature flag IDs, at most 100. Replaces the current list: include every flag to keep. Get the current list from `release-get`.'
            ),
        })
}

const releaseUpdate = (): ToolBase<ReturnType<typeof ReleaseUpdateSchema>, WithPostHogUrl<Schemas.ReleaseDTO>> => ({
    name: 'release-update',
    schema: ReleaseUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ReleaseUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.owner_id !== undefined) {
            body['owner_id'] = params.owner_id
        }
        if (params.feature_flag_ids !== undefined) {
            body['feature_flag_ids'] = params.feature_flag_ids
        }
        if (params.broadcast_ids !== undefined) {
            body['broadcast_ids'] = params.broadcast_ids
        }
        if (params.survey_ids !== undefined) {
            body['survey_ids'] = params.survey_ids
        }
        if (params.insight_ids !== undefined) {
            body['insight_ids'] = params.insight_ids
        }
        if (params.metric_insight_ids !== undefined) {
            body['metric_insight_ids'] = params.metric_insight_ids
        }
        if (params.metric_goals !== undefined) {
            body['metric_goals'] = params.metric_goals
        }
        const result = await context.api.request<Schemas.ReleaseDTO>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/releases/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/releases/${result.id}`)
    },
})

const ReleasesListSchema = () => {
    const ReleasesCatalogReleasesRetrieveQueryParams = orvalSchemas.ReleasesCatalogReleasesRetrieveQueryParams()
    return ReleasesCatalogReleasesRetrieveQueryParams
}

const releasesList = (): ToolBase<
    ReturnType<typeof ReleasesListSchema>,
    WithPostHogUrl<Schemas.CatalogReleasesResponse>
> => ({
    name: 'releases-list',
    schema: ReleasesListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ReleasesListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CatalogReleasesResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/releases/catalog_releases/`,
            query: {
                cursor: params.cursor,
                feature_flag_id: params.feature_flag_id,
                limit: params.limit,
                order: params.order,
                owner: params.owner,
                search: params.search,
            },
        })
        return await withPostHogUrl(
            context,
            {
                ...result,
                results: await Promise.all(
                    (result.results ?? []).map((item) => withPostHogUrl(context, item, `/releases/${item.id}`))
                ),
            },
            '/releases'
        )
    },
})

const ReleasesSuggestForFlagSchema = () => {
    const ReleasesFlagSuggestionsRetrieveQueryParams = orvalSchemas.ReleasesFlagSuggestionsRetrieveQueryParams()
    return ReleasesFlagSuggestionsRetrieveQueryParams
}

const releasesSuggestForFlag = (): ToolBase<ReturnType<typeof ReleasesSuggestForFlagSchema>, Schemas.FlagReleases> => ({
    name: 'releases-suggest-for-flag',
    schema: ReleasesSuggestForFlagSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ReleasesSuggestForFlagSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.FlagReleases>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/releases/flag_suggestions/`,
            query: {
                feature_flag_id: params.feature_flag_id,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'release-create': releaseCreate,
    'release-delete': releaseDelete,
    'release-get': releaseGet,
    'release-merge': releaseMerge,
    'release-update': releaseUpdate,
    'releases-list': releasesList,
    'releases-suggest-for-flag': releasesSuggestForFlag,
}
