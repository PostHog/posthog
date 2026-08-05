// AUTO-GENERATED from products/canvas/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    CanvasesBuildsRetrieveParams,
    CanvasesCreateBody,
    CanvasesEditCreateBody,
    CanvasesEditCreateParams,
    CanvasesListQueryParams,
    CanvasesPublishCreateBody,
    CanvasesPublishCreateParams,
    CanvasesSourceRetrieveParams,
    CanvasesSourceRetrieveQueryParams,
    CanvasesValidateCreateBody,
    CanvasesValidateCreateParams,
} from '@/generated/canvas/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const CanvasBuildsRetrieveSchema = CanvasesBuildsRetrieveParams.omit({ project_id: true }).extend({
    id: CanvasesBuildsRetrieveParams.shape['id'].describe('ID of the canvas whose builds to read.'),
})

const canvasBuildsRetrieve = (): ToolBase<typeof CanvasBuildsRetrieveSchema, Schemas.CanvasBuildsResponse> => ({
    name: 'canvas-builds-retrieve',
    schema: CanvasBuildsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof CanvasBuildsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CanvasBuildsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/canvases/${encodeURIComponent(String(params.id))}/builds/`,
        })
        return result
    },
})

const CanvasCreateSchema = CanvasesCreateBody.extend({
    channel_id: CanvasesCreateBody.shape['channel_id'].describe(
        'Id of the channel to create the canvas in (resolve it with channel-list).'
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
    'canvas-edit-create': canvasEditCreate,
    'canvas-list': canvasList,
    'canvas-publish-create': canvasPublishCreate,
    'canvas-source-retrieve': canvasSourceRetrieve,
    'canvas-validate-create': canvasValidateCreate,
}
