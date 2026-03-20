// AUTO-GENERATED from products/notebooks/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    NotebooksCreateBody,
    NotebooksDestroyParams,
    NotebooksListQueryParams,
    NotebooksPartialUpdateBody,
    NotebooksPartialUpdateParams,
    NotebooksRetrieveParams,
} from '@/generated/notebooks/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const NotebooksListSchema = NotebooksListQueryParams

const notebooksList = (): ToolBase<
    typeof NotebooksListSchema,
    Schemas.PaginatedNotebookMinimalList & { _posthogUrl: string }
> => ({
    name: 'notebooks-list',
    schema: NotebooksListSchema,
    handler: async (context: Context, params: z.infer<typeof NotebooksListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedNotebookMinimalList>({
            method: 'GET',
            path: `/api/projects/${projectId}/notebooks/`,
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
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/notebooks`,
        }
    },
})

const NotebooksCreateSchema = NotebooksCreateBody

const notebooksCreate = (): ToolBase<typeof NotebooksCreateSchema, Schemas.Notebook & { _posthogUrl: string }> => ({
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
            path: `/api/projects/${projectId}/notebooks/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/notebooks/${(result as any).short_id}`,
        }
    },
})

const NotebooksRetrieveSchema = NotebooksRetrieveParams.omit({ project_id: true })

const notebooksRetrieve = (): ToolBase<typeof NotebooksRetrieveSchema, Schemas.Notebook & { _posthogUrl: string }> => ({
    name: 'notebooks-retrieve',
    schema: NotebooksRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof NotebooksRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Notebook>({
            method: 'GET',
            path: `/api/projects/${projectId}/notebooks/${params.short_id}/`,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/notebooks/${(result as any).short_id}`,
        }
    },
})

const NotebooksPartialUpdateSchema = NotebooksPartialUpdateParams.omit({ project_id: true }).extend(
    NotebooksPartialUpdateBody.shape
)

const notebooksPartialUpdate = (): ToolBase<
    typeof NotebooksPartialUpdateSchema,
    Schemas.Notebook & { _posthogUrl: string }
> => ({
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
            path: `/api/projects/${projectId}/notebooks/${params.short_id}/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/notebooks/${(result as any).short_id}`,
        }
    },
})

const NotebooksDestroySchema = NotebooksDestroyParams.omit({ project_id: true })

const notebooksDestroy = (): ToolBase<typeof NotebooksDestroySchema, unknown> => ({
    name: 'notebooks-destroy',
    schema: NotebooksDestroySchema,
    handler: async (context: Context, params: z.infer<typeof NotebooksDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/notebooks/${params.short_id}/`,
            body: { deleted: true },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'notebooks-list': notebooksList,
    'notebooks-create': notebooksCreate,
    'notebooks-retrieve': notebooksRetrieve,
    'notebooks-partial-update': notebooksPartialUpdate,
    'notebooks-destroy': notebooksDestroy,
}
