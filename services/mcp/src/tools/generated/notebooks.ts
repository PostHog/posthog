// AUTO-GENERATED from products/notebooks/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    NotebooksCreateBody,
    NotebooksDestroyParams,
    NotebooksListQueryParams,
    NotebooksMarkdownRetrieveParams,
    NotebooksPartialUpdateBody,
    NotebooksPartialUpdateParams,
    NotebooksRetrieveParams,
} from '@/generated/notebooks/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const NotebooksCreateSchema = NotebooksCreateBody

const notebooksCreate = (): ToolBase<typeof NotebooksCreateSchema, WithPostHogUrl<Schemas.Notebook>> => ({
    name: 'notebooks-create',
    schema: NotebooksCreateSchema,
    handler: async (context: Context, params: z.infer<typeof NotebooksCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        if (params.text_content !== undefined) {
            body['text_content'] = params.text_content
        }
        if (params.version !== undefined) {
            body['version'] = params.version
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        const result = await context.api.request<Schemas.Notebook>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/notebooks/`,
            body,
        })
        return await withPostHogUrl(context, result, `/notebooks/${result.short_id}`)
    },
})

const NotebooksDestroySchema = NotebooksDestroyParams.omit({ project_id: true })

const notebooksDestroy = (): ToolBase<typeof NotebooksDestroySchema, Schemas.Notebook> => ({
    name: 'notebooks-destroy',
    schema: NotebooksDestroySchema,
    handler: async (context: Context, params: z.infer<typeof NotebooksDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Notebook>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/notebooks/${encodeURIComponent(String(params.short_id))}/`,
            body: { deleted: true },
        })
        return result
    },
})

const NotebooksListSchema = NotebooksListQueryParams

const notebooksList = (): ToolBase<
    typeof NotebooksListSchema,
    WithPostHogUrl<Schemas.PaginatedNotebookMinimalList>
> => ({
    name: 'notebooks-list',
    schema: NotebooksListSchema,
    handler: async (context: Context, params: z.infer<typeof NotebooksListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedNotebookMinimalList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/notebooks/`,
            query: {
                contains: params.contains,
                created_by: params.created_by,
                date_from: params.date_from,
                date_to: params.date_to,
                limit: params.limit,
                offset: params.offset,
                user: params.user,
            },
        })
        return await withPostHogUrl(context, result, '/notebooks')
    },
})

const NotebooksMarkdownRetrieveSchema = NotebooksMarkdownRetrieveParams.omit({ project_id: true })

const notebooksMarkdownRetrieve = (): ToolBase<typeof NotebooksMarkdownRetrieveSchema, Schemas.NotebookMarkdown> => ({
    name: 'notebooks-markdown-retrieve',
    schema: NotebooksMarkdownRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof NotebooksMarkdownRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.NotebookMarkdown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/notebooks/${encodeURIComponent(String(params.short_id))}/markdown/`,
        })
        return result
    },
})

const NotebooksPartialUpdateSchema = NotebooksPartialUpdateParams.omit({ project_id: true }).extend(
    NotebooksPartialUpdateBody.shape
)

const notebooksPartialUpdate = (): ToolBase<typeof NotebooksPartialUpdateSchema, WithPostHogUrl<Schemas.Notebook>> => ({
    name: 'notebooks-partial-update',
    schema: NotebooksPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof NotebooksPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        if (params.text_content !== undefined) {
            body['text_content'] = params.text_content
        }
        if (params.version !== undefined) {
            body['version'] = params.version
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        const result = await context.api.request<Schemas.Notebook>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/notebooks/${encodeURIComponent(String(params.short_id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/notebooks/${result.short_id}`)
    },
})

const NotebooksRetrieveSchema = NotebooksRetrieveParams.omit({ project_id: true })

const notebooksRetrieve = (): ToolBase<typeof NotebooksRetrieveSchema, WithPostHogUrl<Schemas.Notebook>> => ({
    name: 'notebooks-retrieve',
    schema: NotebooksRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof NotebooksRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Notebook>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/notebooks/${encodeURIComponent(String(params.short_id))}/`,
        })
        return await withPostHogUrl(context, result, `/notebooks/${result.short_id}`)
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'notebooks-create': notebooksCreate,
    'notebooks-destroy': notebooksDestroy,
    'notebooks-list': notebooksList,
    'notebooks-markdown-retrieve': notebooksMarkdownRetrieve,
    'notebooks-partial-update': notebooksPartialUpdate,
    'notebooks-retrieve': notebooksRetrieve,
}
