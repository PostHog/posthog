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
    NotebooksSqlV2RunCreateBody,
    NotebooksSqlV2RunCreateParams,
    NotebooksSqlV2RunsInterruptCreateParams,
    NotebooksSqlV2RunsRetrieveParams,
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

const NotebooksRunCellSchema = NotebooksSqlV2RunCreateParams.omit({ project_id: true }).extend(
    NotebooksSqlV2RunCreateBody.shape
)

const notebooksRunCell = (): ToolBase<typeof NotebooksRunCellSchema, Schemas.NotebookSQLV2RunResponse> => ({
    name: 'notebooks-run-cell',
    schema: NotebooksRunCellSchema,
    handler: async (context: Context, params: z.infer<typeof NotebooksRunCellSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.node_id !== undefined) {
            body['node_id'] = params.node_id
        }
        if (params.node_type !== undefined) {
            body['node_type'] = params.node_type
        }
        if (params.code !== undefined) {
            body['code'] = params.code
        }
        if (params.output_name !== undefined) {
            body['output_name'] = params.output_name
        }
        if (params.refs !== undefined) {
            body['refs'] = params.refs
        }
        const result = await context.api.request<Schemas.NotebookSQLV2RunResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/notebooks/${encodeURIComponent(String(params.short_id))}/sql_v2/run/`,
            body,
        })
        return result
    },
})

const NotebooksRunCellInterruptSchema = NotebooksSqlV2RunsInterruptCreateParams.omit({ project_id: true })

const notebooksRunCellInterrupt = (): ToolBase<
    typeof NotebooksRunCellInterruptSchema,
    Schemas.NotebookSQLV2InterruptResponse
> => ({
    name: 'notebooks-run-cell-interrupt',
    schema: NotebooksRunCellInterruptSchema,
    handler: async (context: Context, params: z.infer<typeof NotebooksRunCellInterruptSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.NotebookSQLV2InterruptResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/notebooks/${encodeURIComponent(String(params.short_id))}/sql_v2/runs/${encodeURIComponent(String(params.run_id))}/interrupt/`,
        })
        return result
    },
})

const NotebooksRunCellResultSchema = NotebooksSqlV2RunsRetrieveParams.omit({ project_id: true })

const notebooksRunCellResult = (): ToolBase<
    typeof NotebooksRunCellResultSchema,
    Schemas.NotebookSQLV2RunStatusResponse
> => ({
    name: 'notebooks-run-cell-result',
    schema: NotebooksRunCellResultSchema,
    handler: async (context: Context, params: z.infer<typeof NotebooksRunCellResultSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.NotebookSQLV2RunStatusResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/notebooks/${encodeURIComponent(String(params.short_id))}/sql_v2/runs/${encodeURIComponent(String(params.run_id))}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'notebooks-create': notebooksCreate,
    'notebooks-destroy': notebooksDestroy,
    'notebooks-list': notebooksList,
    'notebooks-partial-update': notebooksPartialUpdate,
    'notebooks-retrieve': notebooksRetrieve,
    'notebooks-run-cell': notebooksRunCell,
    'notebooks-run-cell-interrupt': notebooksRunCellInterrupt,
    'notebooks-run-cell-result': notebooksRunCellResult,
}
