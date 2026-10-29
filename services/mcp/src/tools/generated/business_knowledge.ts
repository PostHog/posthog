// AUTO-GENERATED from products/business_knowledge/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/business_knowledge/api'
import { BusinessKnowledgeUrlSourceCreateSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const BusinessKnowledgeDocumentWindowRetrieveSchema = () => {
    const BusinessKnowledgeDocumentsWindowListParams = orvalSchemas.BusinessKnowledgeDocumentsWindowListParams()
    const BusinessKnowledgeDocumentsWindowListQueryParams =
        orvalSchemas.BusinessKnowledgeDocumentsWindowListQueryParams()
    return BusinessKnowledgeDocumentsWindowListParams.omit({ project_id: true }).extend(
        BusinessKnowledgeDocumentsWindowListQueryParams.shape
    )
}

const businessKnowledgeDocumentWindowRetrieve = (): ToolBase<
    ReturnType<typeof BusinessKnowledgeDocumentWindowRetrieveSchema>,
    Schemas.KnowledgeDocumentWindow[]
> => ({
    name: 'business-knowledge-document-window-retrieve',
    schema: BusinessKnowledgeDocumentWindowRetrieveSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof BusinessKnowledgeDocumentWindowRetrieveSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.KnowledgeDocumentWindow[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/business_knowledge/documents/${encodeURIComponent(String(params.id))}/window/`,
            query: {
                around_ordinal: params.around_ordinal,
                radius: params.radius,
            },
        })
        return result
    },
})

const BusinessKnowledgeDocumentsSearchSchema = () => {
    const BusinessKnowledgeDocumentsSearchListQueryParams =
        orvalSchemas.BusinessKnowledgeDocumentsSearchListQueryParams()
    return BusinessKnowledgeDocumentsSearchListQueryParams
}

const businessKnowledgeDocumentsSearch = (): ToolBase<
    ReturnType<typeof BusinessKnowledgeDocumentsSearchSchema>,
    Schemas.KnowledgeSearchResult[]
> => ({
    name: 'business-knowledge-documents-search',
    schema: BusinessKnowledgeDocumentsSearchSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof BusinessKnowledgeDocumentsSearchSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.KnowledgeSearchResult[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/business_knowledge/documents/search/`,
            query: {
                library_id: params.library_id,
                limit: params.limit,
                query: params.query,
                rerank: params.rerank,
            },
        })
        return result
    },
})

const BusinessKnowledgeLibrariesCreateSchema = () => {
    const BusinessKnowledgeLibrariesCreateBody = orvalSchemas.BusinessKnowledgeLibrariesCreateBody()
    return BusinessKnowledgeLibrariesCreateBody
}

const businessKnowledgeLibrariesCreate = (): ToolBase<
    ReturnType<typeof BusinessKnowledgeLibrariesCreateSchema>,
    Schemas.KnowledgeLibrary
> => ({
    name: 'business-knowledge-libraries-create',
    schema: BusinessKnowledgeLibrariesCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof BusinessKnowledgeLibrariesCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        const result = await context.api.request<Schemas.KnowledgeLibrary>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/business_knowledge/libraries/`,
            body,
        })
        return result
    },
})

const BusinessKnowledgeLibrariesDestroySchema = () => {
    const BusinessKnowledgeLibrariesDestroyParams = orvalSchemas.BusinessKnowledgeLibrariesDestroyParams()
    return BusinessKnowledgeLibrariesDestroyParams.omit({ project_id: true })
}

const businessKnowledgeLibrariesDestroy = (): ToolBase<
    ReturnType<typeof BusinessKnowledgeLibrariesDestroySchema>,
    unknown
> => ({
    name: 'business-knowledge-libraries-destroy',
    schema: BusinessKnowledgeLibrariesDestroySchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof BusinessKnowledgeLibrariesDestroySchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/business_knowledge/libraries/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const BusinessKnowledgeLibrariesListSchema = () => z.object({})

const businessKnowledgeLibrariesList = (): ToolBase<
    ReturnType<typeof BusinessKnowledgeLibrariesListSchema>,
    WithPostHogUrl<Schemas.KnowledgeLibrary[]>
> => ({
    name: 'business-knowledge-libraries-list',
    schema: BusinessKnowledgeLibrariesListSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof BusinessKnowledgeLibrariesListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.KnowledgeLibrary[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/business_knowledge/libraries/`,
        })
        return await withPostHogUrl(context, result, '/business-knowledge')
    },
})

const BusinessKnowledgeLibrariesPartialUpdateSchema = () => {
    const BusinessKnowledgeLibrariesPartialUpdateBody = orvalSchemas.BusinessKnowledgeLibrariesPartialUpdateBody()
    const BusinessKnowledgeLibrariesPartialUpdateParams = orvalSchemas.BusinessKnowledgeLibrariesPartialUpdateParams()
    return BusinessKnowledgeLibrariesPartialUpdateParams.omit({ project_id: true }).extend(
        BusinessKnowledgeLibrariesPartialUpdateBody.shape
    )
}

const businessKnowledgeLibrariesPartialUpdate = (): ToolBase<
    ReturnType<typeof BusinessKnowledgeLibrariesPartialUpdateSchema>,
    Schemas.KnowledgeLibrary
> => ({
    name: 'business-knowledge-libraries-partial-update',
    schema: BusinessKnowledgeLibrariesPartialUpdateSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof BusinessKnowledgeLibrariesPartialUpdateSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.source_ids !== undefined) {
            body['source_ids'] = params.source_ids
        }
        if (params.repos !== undefined) {
            body['repos'] = params.repos
        }
        const result = await context.api.request<Schemas.KnowledgeLibrary>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/business_knowledge/libraries/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const BusinessKnowledgeLibrariesRetrieveSchema = () => {
    const BusinessKnowledgeLibrariesRetrieveParams = orvalSchemas.BusinessKnowledgeLibrariesRetrieveParams()
    return BusinessKnowledgeLibrariesRetrieveParams.omit({ project_id: true })
}

const businessKnowledgeLibrariesRetrieve = (): ToolBase<
    ReturnType<typeof BusinessKnowledgeLibrariesRetrieveSchema>,
    Schemas.KnowledgeLibrary
> => ({
    name: 'business-knowledge-libraries-retrieve',
    schema: BusinessKnowledgeLibrariesRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof BusinessKnowledgeLibrariesRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.KnowledgeLibrary>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/business_knowledge/libraries/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const BusinessKnowledgeRepositoriesFileRetrieveSchema = () => {
    const BusinessKnowledgeRepositoriesFileRetrieveQueryParams =
        orvalSchemas.BusinessKnowledgeRepositoriesFileRetrieveQueryParams()
    return BusinessKnowledgeRepositoriesFileRetrieveQueryParams
}

const businessKnowledgeRepositoriesFileRetrieve = (): ToolBase<
    ReturnType<typeof BusinessKnowledgeRepositoriesFileRetrieveSchema>,
    Schemas.RepositoryFile
> => ({
    name: 'business-knowledge-repositories-file-retrieve',
    schema: BusinessKnowledgeRepositoriesFileRetrieveSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof BusinessKnowledgeRepositoriesFileRetrieveSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.RepositoryFile>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/business_knowledge/repositories/file/`,
            query: {
                library_id: params.library_id,
                path: params.path,
                repo: params.repo,
            },
        })
        return result
    },
})

const BusinessKnowledgeRepositoriesSearchSchema = () => {
    const BusinessKnowledgeRepositoriesSearchQueryParams = orvalSchemas.BusinessKnowledgeRepositoriesSearchQueryParams()
    return BusinessKnowledgeRepositoriesSearchQueryParams
}

const businessKnowledgeRepositoriesSearch = (): ToolBase<
    ReturnType<typeof BusinessKnowledgeRepositoriesSearchSchema>,
    Schemas.RepositorySearchResponse
> => ({
    name: 'business-knowledge-repositories-search',
    schema: BusinessKnowledgeRepositoriesSearchSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof BusinessKnowledgeRepositoriesSearchSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.RepositorySearchResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/business_knowledge/repositories/search/`,
            query: {
                library_id: params.library_id,
                query: params.query,
                repo: params.repo,
            },
        })
        return result
    },
})

const BusinessKnowledgeSourcesListSchema = () => {
    const BusinessKnowledgeSourcesListQueryParams = orvalSchemas.BusinessKnowledgeSourcesListQueryParams()
    return BusinessKnowledgeSourcesListQueryParams
}

const businessKnowledgeSourcesList = (): ToolBase<
    ReturnType<typeof BusinessKnowledgeSourcesListSchema>,
    WithPostHogUrl<Schemas.PaginatedKnowledgeSourceList>
> => ({
    name: 'business-knowledge-sources-list',
    schema: BusinessKnowledgeSourcesListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof BusinessKnowledgeSourcesListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedKnowledgeSourceList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/business_knowledge/sources/`,
            query: {
                added_by: params.added_by,
                library_id: params.library_id,
                limit: params.limit,
                offset: params.offset,
                search: params.search,
                source_type: params.source_type,
                unfiled: params.unfiled,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'name',
                    'source_type',
                    'status',
                    'error_message',
                    'document_count',
                    'chunk_count',
                    'source_url',
                    'has_unsafe_documents',
                    'always_include',
                    'refresh_interval',
                    'next_refresh_at',
                    'created_at',
                    'updated_at',
                    'library_ids',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(
            context,
            {
                ...filtered,
                results: await Promise.all(
                    (filtered.results ?? []).map((item) =>
                        withPostHogUrl(context, item, `/business-knowledge/${item.id}`)
                    )
                ),
            },
            '/business-knowledge'
        )
    },
})

const BusinessKnowledgeSourcesPartialUpdateSchema = () => {
    const BusinessKnowledgeSourcesPartialUpdateBody = orvalSchemas.BusinessKnowledgeSourcesPartialUpdateBody()
    const BusinessKnowledgeSourcesPartialUpdateParams = orvalSchemas.BusinessKnowledgeSourcesPartialUpdateParams()
    return BusinessKnowledgeSourcesPartialUpdateParams.omit({ project_id: true }).extend(
        BusinessKnowledgeSourcesPartialUpdateBody.shape
    )
}

const businessKnowledgeSourcesPartialUpdate = (): ToolBase<
    ReturnType<typeof BusinessKnowledgeSourcesPartialUpdateSchema>,
    Schemas.KnowledgeSource
> => ({
    name: 'business-knowledge-sources-partial-update',
    schema: BusinessKnowledgeSourcesPartialUpdateSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof BusinessKnowledgeSourcesPartialUpdateSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.text !== undefined) {
            body['text'] = params.text
        }
        if (params.always_include !== undefined) {
            body['always_include'] = params.always_include
        }
        if (params.library_ids !== undefined) {
            body['library_ids'] = params.library_ids
        }
        const result = await context.api.request<Schemas.KnowledgeSource>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/business_knowledge/sources/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const BusinessKnowledgeSourcesRetrieveSchema = () => {
    const BusinessKnowledgeSourcesRetrieveParams = orvalSchemas.BusinessKnowledgeSourcesRetrieveParams()
    return BusinessKnowledgeSourcesRetrieveParams.omit({ project_id: true })
}

const businessKnowledgeSourcesRetrieve = (): ToolBase<
    ReturnType<typeof BusinessKnowledgeSourcesRetrieveSchema>,
    WithPostHogUrl<Schemas.KnowledgeSource>
> => ({
    name: 'business-knowledge-sources-retrieve',
    schema: BusinessKnowledgeSourcesRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof BusinessKnowledgeSourcesRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.KnowledgeSource>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/business_knowledge/sources/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/business-knowledge/${result.id}`)
    },
})

const BusinessKnowledgeSourcesTextCreateSchema = () => {
    const BusinessKnowledgeSourcesCreateBody = orvalSchemas.BusinessKnowledgeSourcesCreateBody()
    return BusinessKnowledgeSourcesCreateBody
}

const businessKnowledgeSourcesTextCreate = (): ToolBase<
    ReturnType<typeof BusinessKnowledgeSourcesTextCreateSchema>,
    Schemas.KnowledgeSource
> => ({
    name: 'business-knowledge-sources-text-create',
    schema: BusinessKnowledgeSourcesTextCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof BusinessKnowledgeSourcesTextCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.text !== undefined) {
            body['text'] = params.text
        }
        if (params.always_include !== undefined) {
            body['always_include'] = params.always_include
        }
        const result = await context.api.request<Schemas.KnowledgeSource>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/business_knowledge/sources/`,
            body,
        })
        return result
    },
})

const BusinessKnowledgeSourcesUrlCreateSchema = () => BusinessKnowledgeUrlSourceCreateSchema

const businessKnowledgeSourcesUrlCreate = (): ToolBase<
    ReturnType<typeof BusinessKnowledgeSourcesUrlCreateSchema>,
    Schemas.KnowledgeSource
> => ({
    name: 'business-knowledge-sources-url-create',
    schema: BusinessKnowledgeSourcesUrlCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof BusinessKnowledgeSourcesUrlCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const parsedParams = BusinessKnowledgeSourcesUrlCreateSchema().parse(params)
        const result = await context.api.request<Schemas.KnowledgeSource>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/business_knowledge/sources/`,
            body: parsedParams,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'business-knowledge-document-window-retrieve': businessKnowledgeDocumentWindowRetrieve,
    'business-knowledge-documents-search': businessKnowledgeDocumentsSearch,
    'business-knowledge-libraries-create': businessKnowledgeLibrariesCreate,
    'business-knowledge-libraries-destroy': businessKnowledgeLibrariesDestroy,
    'business-knowledge-libraries-list': businessKnowledgeLibrariesList,
    'business-knowledge-libraries-partial-update': businessKnowledgeLibrariesPartialUpdate,
    'business-knowledge-libraries-retrieve': businessKnowledgeLibrariesRetrieve,
    'business-knowledge-repositories-file-retrieve': businessKnowledgeRepositoriesFileRetrieve,
    'business-knowledge-repositories-search': businessKnowledgeRepositoriesSearch,
    'business-knowledge-sources-list': businessKnowledgeSourcesList,
    'business-knowledge-sources-partial-update': businessKnowledgeSourcesPartialUpdate,
    'business-knowledge-sources-retrieve': businessKnowledgeSourcesRetrieve,
    'business-knowledge-sources-text-create': businessKnowledgeSourcesTextCreate,
    'business-knowledge-sources-url-create': businessKnowledgeSourcesUrlCreate,
}
