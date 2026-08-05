// AUTO-GENERATED from products/business_knowledge/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    BusinessKnowledgeDocumentsSearchListQueryParams,
    BusinessKnowledgeDocumentsWindowListParams,
    BusinessKnowledgeDocumentsWindowListQueryParams,
    BusinessKnowledgeSourcesCreateBody,
    BusinessKnowledgeSourcesListQueryParams,
    BusinessKnowledgeSourcesPartialUpdateBody,
    BusinessKnowledgeSourcesPartialUpdateParams,
    BusinessKnowledgeSourcesRetrieveParams,
} from '@/generated/business_knowledge/api'
import { BusinessKnowledgeUrlSourceCreateSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const BusinessKnowledgeDocumentWindowRetrieveSchema = BusinessKnowledgeDocumentsWindowListParams.omit({
    project_id: true,
}).extend(BusinessKnowledgeDocumentsWindowListQueryParams.shape)

const businessKnowledgeDocumentWindowRetrieve = (): ToolBase<
    typeof BusinessKnowledgeDocumentWindowRetrieveSchema,
    Schemas.KnowledgeDocumentWindow[]
> => ({
    name: 'business-knowledge-document-window-retrieve',
    schema: BusinessKnowledgeDocumentWindowRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof BusinessKnowledgeDocumentWindowRetrieveSchema>) => {
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

const BusinessKnowledgeDocumentsSearchSchema = BusinessKnowledgeDocumentsSearchListQueryParams

const businessKnowledgeDocumentsSearch = (): ToolBase<
    typeof BusinessKnowledgeDocumentsSearchSchema,
    Schemas.KnowledgeSearchResult[]
> => ({
    name: 'business-knowledge-documents-search',
    schema: BusinessKnowledgeDocumentsSearchSchema,
    handler: async (context: Context, params: z.infer<typeof BusinessKnowledgeDocumentsSearchSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.KnowledgeSearchResult[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/business_knowledge/documents/search/`,
            query: {
                limit: params.limit,
                query: params.query,
                rerank: params.rerank,
            },
        })
        return result
    },
})

const BusinessKnowledgeSourcesListSchema = BusinessKnowledgeSourcesListQueryParams

const businessKnowledgeSourcesList = (): ToolBase<
    typeof BusinessKnowledgeSourcesListSchema,
    WithPostHogUrl<Schemas.PaginatedKnowledgeSourceList>
> => ({
    name: 'business-knowledge-sources-list',
    schema: BusinessKnowledgeSourcesListSchema,
    handler: async (context: Context, params: z.infer<typeof BusinessKnowledgeSourcesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedKnowledgeSourceList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/business_knowledge/sources/`,
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
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/business-knowledge')
    },
})

const BusinessKnowledgeSourcesPartialUpdateSchema = BusinessKnowledgeSourcesPartialUpdateParams.omit({
    project_id: true,
}).extend(BusinessKnowledgeSourcesPartialUpdateBody.shape)

const businessKnowledgeSourcesPartialUpdate = (): ToolBase<
    typeof BusinessKnowledgeSourcesPartialUpdateSchema,
    Schemas.KnowledgeSource
> => ({
    name: 'business-knowledge-sources-partial-update',
    schema: BusinessKnowledgeSourcesPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof BusinessKnowledgeSourcesPartialUpdateSchema>) => {
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
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/business_knowledge/sources/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const BusinessKnowledgeSourcesRetrieveSchema = BusinessKnowledgeSourcesRetrieveParams.omit({ project_id: true })

const businessKnowledgeSourcesRetrieve = (): ToolBase<
    typeof BusinessKnowledgeSourcesRetrieveSchema,
    Schemas.KnowledgeSource
> => ({
    name: 'business-knowledge-sources-retrieve',
    schema: BusinessKnowledgeSourcesRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof BusinessKnowledgeSourcesRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.KnowledgeSource>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/business_knowledge/sources/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const BusinessKnowledgeSourcesTextCreateSchema = BusinessKnowledgeSourcesCreateBody

const businessKnowledgeSourcesTextCreate = (): ToolBase<
    typeof BusinessKnowledgeSourcesTextCreateSchema,
    Schemas.KnowledgeSource
> => ({
    name: 'business-knowledge-sources-text-create',
    schema: BusinessKnowledgeSourcesTextCreateSchema,
    handler: async (context: Context, params: z.infer<typeof BusinessKnowledgeSourcesTextCreateSchema>) => {
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

const BusinessKnowledgeSourcesUrlCreateSchema = BusinessKnowledgeUrlSourceCreateSchema

const businessKnowledgeSourcesUrlCreate = (): ToolBase<
    typeof BusinessKnowledgeSourcesUrlCreateSchema,
    Schemas.KnowledgeSource
> => ({
    name: 'business-knowledge-sources-url-create',
    schema: BusinessKnowledgeSourcesUrlCreateSchema,
    handler: async (context: Context, params: z.infer<typeof BusinessKnowledgeSourcesUrlCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const parsedParams = BusinessKnowledgeSourcesUrlCreateSchema.parse(params)
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
    'business-knowledge-sources-list': businessKnowledgeSourcesList,
    'business-knowledge-sources-partial-update': businessKnowledgeSourcesPartialUpdate,
    'business-knowledge-sources-retrieve': businessKnowledgeSourcesRetrieve,
    'business-knowledge-sources-text-create': businessKnowledgeSourcesTextCreate,
    'business-knowledge-sources-url-create': businessKnowledgeSourcesUrlCreate,
}
