// AUTO-GENERATED from products/canvas/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/canvas/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const CanvasBuildsRetrieveSchema = () => {
    const CanvasesBuildsRetrieveParams = orvalSchemas.CanvasesBuildsRetrieveParams()
    const CanvasesBuildsRetrieveQueryParams = orvalSchemas.CanvasesBuildsRetrieveQueryParams()
    return CanvasesBuildsRetrieveParams.omit({ project_id: true })
        .extend(CanvasesBuildsRetrieveQueryParams.shape)
        .extend({ id: CanvasesBuildsRetrieveParams.shape['id'].describe('ID of the canvas whose builds to read.') })
}

const canvasBuildsRetrieve = (): ToolBase<
    ReturnType<typeof CanvasBuildsRetrieveSchema>,
    Schemas.CanvasBuildsResponse
> => ({
    name: 'canvas-builds-retrieve',
    schema: CanvasBuildsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CanvasBuildsRetrieveSchema>>) => {
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

const CanvasCreateSchema = () => {
    const CanvasesCreateBody = orvalSchemas.CanvasesCreateBody()
    return CanvasesCreateBody.extend({
        channel_id: CanvasesCreateBody.shape['channel_id'].describe(
            "Id of the channel to create the canvas in — the channel the task was created in, from the task's context. Use channel-list only to resolve a channel the user named; never pick a channel from the listing yourself (the personal #me channel is not a default)."
        ),
        kind: CanvasesCreateBody.shape['kind'].describe(
            "What to create: 'freeform' (a standalone app — the default), 'component' (a reusable widget for grid canvases; its published project must declare a `component` placement contract), or 'grid' (a composition of components, edited via canvas-layout-patch). See canvas-list (kind=component) before creating a component."
        ),
        description: CanvasesCreateBody.shape['description'].describe(
            'Short prose describing the canvas. For components this is the store-search text — say what the widget shows and what its config controls, so future searches find it.'
        ),
    })
}

const canvasCreate = (): ToolBase<ReturnType<typeof CanvasCreateSchema>, Schemas.Canvas> => ({
    name: 'canvas-create',
    schema: CanvasCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CanvasCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.channel_id !== undefined) {
            body['channel_id'] = params.channel_id
        }
        if (params.kind !== undefined) {
            body['kind'] = params.kind
        }
        if (params.description !== undefined) {
            body['description'] = params.description
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

const CanvasDraftCreateSchema = () => {
    const CanvasesDraftCreateBody = orvalSchemas.CanvasesDraftCreateBody()
    const CanvasesDraftCreateParams = orvalSchemas.CanvasesDraftCreateParams()
    return CanvasesDraftCreateParams.omit({ project_id: true })
        .extend(CanvasesDraftCreateBody.shape)
        .extend({ id: CanvasesDraftCreateParams.shape['id'].describe('ID of the canvas to stage a draft for.') })
}

const canvasDraftCreate = (): ToolBase<
    ReturnType<typeof CanvasDraftCreateSchema>,
    Schemas.CanvasSourceDraftResponse
> => ({
    name: 'canvas-draft-create',
    schema: CanvasDraftCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CanvasDraftCreateSchema>>) => {
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

const CanvasDraftsRetrieveSchema = () => {
    const CanvasesDraftsRetrieveParams = orvalSchemas.CanvasesDraftsRetrieveParams()
    const CanvasesDraftsRetrieveQueryParams = orvalSchemas.CanvasesDraftsRetrieveQueryParams()
    return CanvasesDraftsRetrieveParams.omit({ project_id: true })
        .extend(CanvasesDraftsRetrieveQueryParams.shape)
        .extend({ id: CanvasesDraftsRetrieveParams.shape['id'].describe('ID of the canvas whose drafts to list.') })
}

const canvasDraftsRetrieve = (): ToolBase<
    ReturnType<typeof CanvasDraftsRetrieveSchema>,
    Schemas.PaginatedCanvasDraftList
> => ({
    name: 'canvas-drafts-retrieve',
    schema: CanvasDraftsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CanvasDraftsRetrieveSchema>>) => {
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

const CanvasEditCreateSchema = () => {
    const CanvasesEditCreateBody = orvalSchemas.CanvasesEditCreateBody()
    const CanvasesEditCreateParams = orvalSchemas.CanvasesEditCreateParams()
    return CanvasesEditCreateParams.omit({ project_id: true })
        .extend(CanvasesEditCreateBody.shape)
        .extend({ id: CanvasesEditCreateParams.shape['id'].describe('ID of the canvas whose source to edit.') })
}

const canvasEditCreate = (): ToolBase<
    ReturnType<typeof CanvasEditCreateSchema>,
    Schemas.CanvasSourcePublishResponse
> => ({
    name: 'canvas-edit-create',
    schema: CanvasEditCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CanvasEditCreateSchema>>) => {
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

const CanvasLayoutGetSchema = () => {
    const CanvasesLayoutRetrieveParams = orvalSchemas.CanvasesLayoutRetrieveParams()
    return CanvasesLayoutRetrieveParams.omit({ project_id: true }).extend({
        id: CanvasesLayoutRetrieveParams.shape['id'].describe('ID of the grid canvas whose layout to read.'),
    })
}

const canvasLayoutGet = (): ToolBase<ReturnType<typeof CanvasLayoutGetSchema>, Schemas.CanvasLayoutResponse> => ({
    name: 'canvas-layout-get',
    schema: CanvasLayoutGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CanvasLayoutGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CanvasLayoutResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/canvases/${encodeURIComponent(String(params.id))}/layout/`,
        })
        return result
    },
})

const CanvasLayoutPatchSchema = () => {
    const CanvasesLayoutPatchCreateBody = orvalSchemas.CanvasesLayoutPatchCreateBody()
    const CanvasesLayoutPatchCreateParams = orvalSchemas.CanvasesLayoutPatchCreateParams()
    return CanvasesLayoutPatchCreateParams.omit({ project_id: true })
        .extend(CanvasesLayoutPatchCreateBody.shape)
        .extend({
            id: CanvasesLayoutPatchCreateParams.shape['id'].describe('ID of the grid canvas whose layout to patch.'),
        })
}

const canvasLayoutPatch = (): ToolBase<
    ReturnType<typeof CanvasLayoutPatchSchema>,
    Schemas.CanvasLayoutPublishResponse
> => ({
    name: 'canvas-layout-patch',
    schema: CanvasLayoutPatchSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CanvasLayoutPatchSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.operations !== undefined) {
            body['operations'] = params.operations
        }
        if (params.prompt !== undefined) {
            body['prompt'] = params.prompt
        }
        if (params.expected_current_version_id !== undefined) {
            body['expected_current_version_id'] = params.expected_current_version_id
        }
        const result = await context.api.request<Schemas.CanvasLayoutPublishResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/canvases/${encodeURIComponent(String(params.id))}/layout/patch/`,
            body,
        })
        return result
    },
})

const CanvasLayoutPublishSchema = () => {
    const CanvasesLayoutPublishCreateBody = orvalSchemas.CanvasesLayoutPublishCreateBody()
    const CanvasesLayoutPublishCreateParams = orvalSchemas.CanvasesLayoutPublishCreateParams()
    return CanvasesLayoutPublishCreateParams.omit({ project_id: true })
        .extend(CanvasesLayoutPublishCreateBody.shape)
        .extend({
            id: CanvasesLayoutPublishCreateParams.shape['id'].describe(
                'ID of the grid canvas whose layout to publish.'
            ),
            expected_current_version_id: CanvasesLayoutPublishCreateBody.shape['expected_current_version_id']
                .unwrap()
                .describe(
                    'The `current_version_id` this document was built on, from canvas-layout-get (null only for a grid canvas that has never published a layout). A whole document replaces the head, so without the guard a layout the user changed after you read it is silently discarded.'
                ),
        })
}

const canvasLayoutPublish = (): ToolBase<
    ReturnType<typeof CanvasLayoutPublishSchema>,
    Schemas.CanvasLayoutPublishResponse
> => ({
    name: 'canvas-layout-publish',
    schema: CanvasLayoutPublishSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CanvasLayoutPublishSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.layout !== undefined) {
            body['layout'] = params.layout
        }
        if (params.prompt !== undefined) {
            body['prompt'] = params.prompt
        }
        if (params.expected_current_version_id !== undefined) {
            body['expected_current_version_id'] = params.expected_current_version_id
        }
        const result = await context.api.request<Schemas.CanvasLayoutPublishResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/canvases/${encodeURIComponent(String(params.id))}/layout/publish/`,
            body,
        })
        return result
    },
})

const CanvasListSchema = () => {
    const CanvasesListQueryParams = orvalSchemas.CanvasesListQueryParams()
    return CanvasesListQueryParams.extend({
        channel: CanvasesListQueryParams.shape['channel'].describe(
            'Only return canvases in this channel (channel id).'
        ),
        kind: CanvasesListQueryParams.shape['kind'].describe(
            'Only return canvases of this kind. kind=component lists the component store.'
        ),
        search: CanvasesListQueryParams.shape['search'].describe(
            'Case-insensitive match on name and description — use to find store components by what they show.'
        ),
    })
}

const canvasList = (): ToolBase<ReturnType<typeof CanvasListSchema>, Schemas.PaginatedCanvasList> => ({
    name: 'canvas-list',
    schema: CanvasListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CanvasListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedCanvasList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/canvases/`,
            query: {
                channel: params.channel,
                kind: params.kind,
                limit: params.limit,
                offset: params.offset,
                search: params.search,
            },
        })
        return result
    },
})

const CanvasMoveSchema = () => {
    const CanvasesPartialUpdateBody = orvalSchemas.CanvasesPartialUpdateBody()
    const CanvasesPartialUpdateParams = orvalSchemas.CanvasesPartialUpdateParams()
    return CanvasesPartialUpdateParams.omit({ project_id: true })
        .extend(
            CanvasesPartialUpdateBody.omit({
                name: true,
                context: true,
                description: true,
                pinned: true,
                generation_task_id: true,
            }).shape
        )
        .extend({
            id: CanvasesPartialUpdateParams.shape['id'].describe('ID of the canvas to move.'),
            channel_id: CanvasesPartialUpdateBody.shape['channel_id']
                .unwrap()
                .describe('ID of the visible destination space.'),
        })
}

const canvasMove = (): ToolBase<ReturnType<typeof CanvasMoveSchema>, Schemas.Canvas> => ({
    name: 'canvas-move',
    schema: CanvasMoveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CanvasMoveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.channel_id !== undefined) {
            body['channel_id'] = params.channel_id
        }
        const result = await context.api.request<Schemas.Canvas>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/canvases/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const CanvasPromoteCreateSchema = () => {
    const CanvasesPromoteCreateBody = orvalSchemas.CanvasesPromoteCreateBody()
    const CanvasesPromoteCreateParams = orvalSchemas.CanvasesPromoteCreateParams()
    return CanvasesPromoteCreateParams.omit({ project_id: true })
        .extend(CanvasesPromoteCreateBody.shape)
        .extend({ id: CanvasesPromoteCreateParams.shape['id'].describe('ID of the canvas whose draft to promote.') })
}

const canvasPromoteCreate = (): ToolBase<ReturnType<typeof CanvasPromoteCreateSchema>, Schemas.CanvasBuild> => ({
    name: 'canvas-promote-create',
    schema: CanvasPromoteCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CanvasPromoteCreateSchema>>) => {
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

const CanvasPublishCreateSchema = () => {
    const CanvasesPublishCreateBody = orvalSchemas.CanvasesPublishCreateBody()
    const CanvasesPublishCreateParams = orvalSchemas.CanvasesPublishCreateParams()
    return CanvasesPublishCreateParams.omit({ project_id: true })
        .extend(CanvasesPublishCreateBody.shape)
        .extend({ id: CanvasesPublishCreateParams.shape['id'].describe('ID of the canvas whose source to publish.') })
}

const canvasPublishCreate = (): ToolBase<
    ReturnType<typeof CanvasPublishCreateSchema>,
    Schemas.CanvasSourcePublishResponse
> => ({
    name: 'canvas-publish-create',
    schema: CanvasPublishCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CanvasPublishCreateSchema>>) => {
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

const CanvasPublishCurrentVersionSchema = () => {
    const CanvasesPublishCurrentVersionCreateBody = orvalSchemas.CanvasesPublishCurrentVersionCreateBody()
    const CanvasesPublishCurrentVersionCreateParams = orvalSchemas.CanvasesPublishCurrentVersionCreateParams()
    return CanvasesPublishCurrentVersionCreateParams.omit({ project_id: true }).extend(
        CanvasesPublishCurrentVersionCreateBody.shape
    )
}

const canvasPublishCurrentVersion = (): ToolBase<
    ReturnType<typeof CanvasPublishCurrentVersionSchema>,
    Schemas.CanvasBuild
> => ({
    name: 'canvas-publish-current-version',
    schema: CanvasPublishCurrentVersionSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CanvasPublishCurrentVersionSchema>>) => {
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

const CanvasSourceRetrieveSchema = () => {
    const CanvasesSourceRetrieveParams = orvalSchemas.CanvasesSourceRetrieveParams()
    const CanvasesSourceRetrieveQueryParams = orvalSchemas.CanvasesSourceRetrieveQueryParams()
    return CanvasesSourceRetrieveParams.omit({ project_id: true })
        .extend(CanvasesSourceRetrieveQueryParams.shape)
        .extend({ id: CanvasesSourceRetrieveParams.shape['id'].describe('ID of the canvas whose source to read.') })
}

const canvasSourceRetrieve = (): ToolBase<
    ReturnType<typeof CanvasSourceRetrieveSchema>,
    Schemas.CanvasSourceResponse
> => ({
    name: 'canvas-source-retrieve',
    schema: CanvasSourceRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CanvasSourceRetrieveSchema>>) => {
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

const CanvasStateRetrieveSchema = () => {
    const CanvasesStateRetrieveParams = orvalSchemas.CanvasesStateRetrieveParams()
    const CanvasesStateRetrieveQueryParams = orvalSchemas.CanvasesStateRetrieveQueryParams()
    return CanvasesStateRetrieveParams.omit({ project_id: true }).extend(CanvasesStateRetrieveQueryParams.shape)
}

const canvasStateRetrieve = (): ToolBase<
    ReturnType<typeof CanvasStateRetrieveSchema>,
    Schemas.CanvasStateResponse
> => ({
    name: 'canvas-state-retrieve',
    schema: CanvasStateRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CanvasStateRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CanvasStateResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/canvases/${encodeURIComponent(String(params.id))}/state/`,
            query: {
                scope: params.scope,
            },
        })
        return result
    },
})

const CanvasStateSetSchema = () => {
    const CanvasesStateSetBody = orvalSchemas.CanvasesStateSetBody()
    const CanvasesStateSetParams = orvalSchemas.CanvasesStateSetParams()
    return CanvasesStateSetParams.omit({ project_id: true }).extend(CanvasesStateSetBody.shape)
}

const canvasStateSet = (): ToolBase<ReturnType<typeof CanvasStateSetSchema>, Schemas.CanvasStateEntry> => ({
    name: 'canvas-state-set',
    schema: CanvasStateSetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CanvasStateSetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.scope !== undefined) {
            body['scope'] = params.scope
        }
        if (params.key !== undefined) {
            body['key'] = params.key
        }
        if (params.value !== undefined) {
            body['value'] = params.value
        }
        const result = await context.api.request<Schemas.CanvasStateEntry>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/canvases/${encodeURIComponent(String(params.id))}/state/set/`,
            body,
        })
        return result
    },
})

const CanvasValidateCreateSchema = () => {
    const CanvasesValidateCreateBody = orvalSchemas.CanvasesValidateCreateBody()
    const CanvasesValidateCreateParams = orvalSchemas.CanvasesValidateCreateParams()
    return CanvasesValidateCreateParams.omit({ project_id: true })
        .extend(CanvasesValidateCreateBody.shape)
        .extend({ id: CanvasesValidateCreateParams.shape['id'].describe('ID of the canvas the project is for.') })
}

const canvasValidateCreate = (): ToolBase<
    ReturnType<typeof CanvasValidateCreateSchema>,
    Schemas.CanvasValidateResponse
> => ({
    name: 'canvas-validate-create',
    schema: CanvasValidateCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CanvasValidateCreateSchema>>) => {
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
    'canvas-layout-get': canvasLayoutGet,
    'canvas-layout-patch': canvasLayoutPatch,
    'canvas-layout-publish': canvasLayoutPublish,
    'canvas-list': canvasList,
    'canvas-move': canvasMove,
    'canvas-promote-create': canvasPromoteCreate,
    'canvas-publish-create': canvasPublishCreate,
    'canvas-publish-current-version': canvasPublishCurrentVersion,
    'canvas-source-retrieve': canvasSourceRetrieve,
    'canvas-state-retrieve': canvasStateRetrieve,
    'canvas-state-set': canvasStateSet,
    'canvas-validate-create': canvasValidateCreate,
}
