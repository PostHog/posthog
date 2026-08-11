// AUTO-GENERATED from products/canvas/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    CanvasesBuildsRetrieveParams,
    CanvasesBuildsRetrieveQueryParams,
    CanvasesCreateBody,
    CanvasesDraftCreateBody,
    CanvasesDraftCreateParams,
    CanvasesDraftsRetrieveParams,
    CanvasesDraftsRetrieveQueryParams,
    CanvasesEditCreateBody,
    CanvasesEditCreateParams,
    CanvasesListQueryParams,
    CanvasesPromoteCreateBody,
    CanvasesPromoteCreateParams,
    CanvasesPublishCreateBody,
    CanvasesPublishCreateParams,
    CanvasesPublishCurrentVersionCreateBody,
    CanvasesPublishCurrentVersionCreateParams,
    CanvasesSourceRetrieveParams,
    CanvasesSourceRetrieveQueryParams,
    CanvasesValidateCreateBody,
    CanvasesValidateCreateParams,
} from '@/generated/canvas/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const CanvasBuildsRetrieveSchema = CanvasesBuildsRetrieveParams.omit({ project_id: true })
    .extend(CanvasesBuildsRetrieveQueryParams.shape)
    .extend({ id: CanvasesBuildsRetrieveParams.shape['id'].describe('ID of the canvas whose builds to read.') })

const canvasBuildsRetrieve = (): ToolBase<typeof CanvasBuildsRetrieveSchema, Schemas.CanvasBuildsResponse> => ({
    name: 'canvas-builds-retrieve',
    schema: CanvasBuildsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof CanvasBuildsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CanvasBuildsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/canvases/${encodeURIComponent(String(params.id))}/builds/`,
            query: {
                version_id: params.version_id,
            },
        })
        return result
    },
})

const CanvasCreateSchema = CanvasesCreateBody.extend({
    channel_id: CanvasesCreateBody.shape['channel_id'].describe(
        "Id of the channel to create the canvas in — the channel the task was created in, from the task's context. Use channel-list only to resolve a channel the user named; never pick a channel from the listing yourself (the personal #me channel is not a default)."
    ),
})

const canvasCreate = (): ToolBase<typeof CanvasCreateSchema, Schemas.Canvas> => ({
    name: 'canvas-create',
    schema: CanvasCreateSchema,
    handler: async (context: Context, params: z.infer<typeof CanvasCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.channel_id !== undefined) {
            body['channel_id'] = params.channel_id
        }
        if (params.template_id !== undefined) {
            body['template_id'] = params.template_id
        }
        const result = await context.api.request<Schemas.Canvas>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/canvases/`,
            body,
        })
        return result
    },
})

const CanvasDraftCreateSchema = CanvasesDraftCreateParams.omit({ project_id: true })
    .extend(CanvasesDraftCreateBody.shape)
    .extend({ id: CanvasesDraftCreateParams.shape['id'].describe('ID of the canvas to stage a draft for.') })

const canvasDraftCreate = (): ToolBase<typeof CanvasDraftCreateSchema, Schemas.CanvasSourceDraftResponse> => ({
    name: 'canvas-draft-create',
    schema: CanvasDraftCreateSchema,
    handler: async (context: Context, params: z.infer<typeof CanvasDraftCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.project !== undefined) {
            body['project'] = params.project
        }
        if (params.prompt !== undefined) {
            body['prompt'] = params.prompt
        }
        const result = await context.api.request<Schemas.CanvasSourceDraftResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/canvases/${encodeURIComponent(String(params.id))}/draft/`,
            body,
        })
        return result
    },
})

const CanvasDraftsRetrieveSchema = CanvasesDraftsRetrieveParams.omit({ project_id: true })
    .extend(CanvasesDraftsRetrieveQueryParams.shape)
    .extend({ id: CanvasesDraftsRetrieveParams.shape['id'].describe('ID of the canvas whose drafts to list.') })

const canvasDraftsRetrieve = (): ToolBase<typeof CanvasDraftsRetrieveSchema, Schemas.PaginatedCanvasDraftList> => ({
    name: 'canvas-drafts-retrieve',
    schema: CanvasDraftsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof CanvasDraftsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedCanvasDraftList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/canvases/${encodeURIComponent(String(params.id))}/drafts/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const CanvasEditCreateSchema = CanvasesEditCreateParams.omit({ project_id: true })
    .extend(CanvasesEditCreateBody.shape)
    .extend({ id: CanvasesEditCreateParams.shape['id'].describe('ID of the canvas whose source to edit.') })

const canvasEditCreate = (): ToolBase<typeof CanvasEditCreateSchema, Schemas.CanvasSourcePublishResponse> => ({
    name: 'canvas-edit-create',
    schema: CanvasEditCreateSchema,
    handler: async (context: Context, params: z.infer<typeof CanvasEditCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.operations !== undefined) {
            body['operations'] = params.operations
        }
        if (params.prompt !== undefined) {
            body['prompt'] = params.prompt
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.expected_current_version_id !== undefined) {
            body['expected_current_version_id'] = params.expected_current_version_id
        }
        const result = await context.api.request<Schemas.CanvasSourcePublishResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/canvases/${encodeURIComponent(String(params.id))}/edit/`,
            body,
        })
        return result
    },
})

const CanvasListSchema = CanvasesListQueryParams.extend({
    channel: CanvasesListQueryParams.shape['channel'].describe('Only return canvases in this channel (channel id).'),
})

const canvasList = (): ToolBase<typeof CanvasListSchema, Schemas.PaginatedCanvasList> => ({
    name: 'canvas-list',
    schema: CanvasListSchema,
    handler: async (context: Context, params: z.infer<typeof CanvasListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedCanvasList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/canvases/`,
            query: {
                channel: params.channel,
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const CanvasPromoteCreateSchema = CanvasesPromoteCreateParams.omit({ project_id: true })
    .extend(CanvasesPromoteCreateBody.shape)
    .extend({ id: CanvasesPromoteCreateParams.shape['id'].describe('ID of the canvas whose draft to promote.') })

const canvasPromoteCreate = (): ToolBase<typeof CanvasPromoteCreateSchema, Schemas.CanvasBuild> => ({
    name: 'canvas-promote-create',
    schema: CanvasPromoteCreateSchema,
    handler: async (context: Context, params: z.infer<typeof CanvasPromoteCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.version_id !== undefined) {
            body['version_id'] = params.version_id
        }
        if (params.expected_current_version_id !== undefined) {
            body['expected_current_version_id'] = params.expected_current_version_id
        }
        const result = await context.api.request<Schemas.CanvasBuild>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/canvases/${encodeURIComponent(String(params.id))}/promote/`,
            body,
        })
        return result
    },
})

const CanvasPublishCreateSchema = CanvasesPublishCreateParams.omit({ project_id: true })
    .extend(CanvasesPublishCreateBody.shape)
    .extend({ id: CanvasesPublishCreateParams.shape['id'].describe('ID of the canvas whose source to publish.') })

const canvasPublishCreate = (): ToolBase<typeof CanvasPublishCreateSchema, Schemas.CanvasSourcePublishResponse> => ({
    name: 'canvas-publish-create',
    schema: CanvasPublishCreateSchema,
    handler: async (context: Context, params: z.infer<typeof CanvasPublishCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.project !== undefined) {
            body['project'] = params.project
        }
        if (params.prompt !== undefined) {
            body['prompt'] = params.prompt
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.expected_current_version_id !== undefined) {
            body['expected_current_version_id'] = params.expected_current_version_id
        }
        const result = await context.api.request<Schemas.CanvasSourcePublishResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/canvases/${encodeURIComponent(String(params.id))}/publish/`,
            body,
        })
        return result
    },
})

const CanvasPublishCurrentVersionSchema = CanvasesPublishCurrentVersionCreateParams.omit({ project_id: true }).extend(
    CanvasesPublishCurrentVersionCreateBody.shape
)

const canvasPublishCurrentVersion = (): ToolBase<typeof CanvasPublishCurrentVersionSchema, Schemas.CanvasBuild> => ({
    name: 'canvas-publish-current-version',
    schema: CanvasPublishCurrentVersionSchema,
    handler: async (context: Context, params: z.infer<typeof CanvasPublishCurrentVersionSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.expected_current_version_id !== undefined) {
            body['expected_current_version_id'] = params.expected_current_version_id
        }
        const result = await context.api.request<Schemas.CanvasBuild>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/canvases/${encodeURIComponent(String(params.id))}/publish-current-version/`,
            body,
        })
        return result
    },
})

const CanvasSourceRetrieveSchema = CanvasesSourceRetrieveParams.omit({ project_id: true })
    .extend(CanvasesSourceRetrieveQueryParams.shape)
    .extend({ id: CanvasesSourceRetrieveParams.shape['id'].describe('ID of the canvas whose source to read.') })

const canvasSourceRetrieve = (): ToolBase<typeof CanvasSourceRetrieveSchema, Schemas.CanvasSourceResponse> => ({
    name: 'canvas-source-retrieve',
    schema: CanvasSourceRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof CanvasSourceRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CanvasSourceResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/canvases/${encodeURIComponent(String(params.id))}/source/`,
            query: {
                version_id: params.version_id,
            },
        })
        return result
    },
})

const CanvasValidateCreateSchema = CanvasesValidateCreateParams.omit({ project_id: true })
    .extend(CanvasesValidateCreateBody.shape)
    .extend({ id: CanvasesValidateCreateParams.shape['id'].describe('ID of the canvas the project is for.') })

const canvasValidateCreate = (): ToolBase<typeof CanvasValidateCreateSchema, Schemas.CanvasValidateResponse> => ({
    name: 'canvas-validate-create',
    schema: CanvasValidateCreateSchema,
    handler: async (context: Context, params: z.infer<typeof CanvasValidateCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.project !== undefined) {
            body['project'] = params.project
        }
        const result = await context.api.request<Schemas.CanvasValidateResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/canvases/${encodeURIComponent(String(params.id))}/validate/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'canvas-builds-retrieve': canvasBuildsRetrieve,
    'canvas-create': canvasCreate,
    'canvas-draft-create': canvasDraftCreate,
    'canvas-drafts-retrieve': canvasDraftsRetrieve,
    'canvas-edit-create': canvasEditCreate,
    'canvas-list': canvasList,
    'canvas-promote-create': canvasPromoteCreate,
    'canvas-publish-create': canvasPublishCreate,
    'canvas-publish-current-version': canvasPublishCurrentVersion,
    'canvas-source-retrieve': canvasSourceRetrieve,
    'canvas-validate-create': canvasValidateCreate,
}
