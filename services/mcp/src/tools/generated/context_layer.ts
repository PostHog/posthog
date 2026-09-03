// AUTO-GENERATED from products/context_layer/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/context_layer/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ContextWikiChannelResolveSchema = () => {
    const ContextLayerAgentChannelPagesRetrieveParams = orvalSchemas.ContextLayerAgentChannelPagesRetrieveParams()
    return ContextLayerAgentChannelPagesRetrieveParams.omit({ project_id: true })
}

const contextWikiChannelResolve = (): ToolBase<
    ReturnType<typeof ContextWikiChannelResolveSchema>,
    Schemas.ChannelWikiPage
> => ({
    name: 'context-wiki-channel-resolve',
    schema: ContextWikiChannelResolveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ContextWikiChannelResolveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ChannelWikiPage>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/context_layer/agent/channel-pages/${encodeURIComponent(String(params.channel_id))}/`,
        })
        return result
    },
})

const ContextWikiPageRetrieveSchema = () => {
    const ContextLayerAgentPagesRetrieveQueryParams = orvalSchemas.ContextLayerAgentPagesRetrieveQueryParams()
    return ContextLayerAgentPagesRetrieveQueryParams
}

const contextWikiPageRetrieve = (): ToolBase<ReturnType<typeof ContextWikiPageRetrieveSchema>, Schemas.WikiPage> => ({
    name: 'context-wiki-page-retrieve',
    schema: ContextWikiPageRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ContextWikiPageRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.WikiPage>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/context_layer/agent/pages/`,
            query: {
                path: params.path,
            },
        })
        return result
    },
})

const ContextWikiPageUpdateSchema = () => {
    const ContextLayerAgentPagesUpdateBody = orvalSchemas.ContextLayerAgentPagesUpdateBody()
    return ContextLayerAgentPagesUpdateBody
}

const contextWikiPageUpdate = (): ToolBase<
    ReturnType<typeof ContextWikiPageUpdateSchema>,
    Schemas.ContextLayerStatus
> => ({
    name: 'context-wiki-page-update',
    schema: ContextWikiPageUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ContextWikiPageUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.path !== undefined) {
            body['path'] = params.path
        }
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        if (params.base_head !== undefined) {
            body['base_head'] = params.base_head
        }
        const result = await context.api.request<Schemas.ContextLayerStatus>({
            method: 'PUT',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/context_layer/agent/pages/`,
            body,
        })
        return result
    },
})

const TaskContextWikiChannelResolveSchema = () => {
    const ContextLayerAgentChannelPagesRetrieveParams = orvalSchemas.ContextLayerAgentChannelPagesRetrieveParams()
    return ContextLayerAgentChannelPagesRetrieveParams.omit({ project_id: true })
}

const taskContextWikiChannelResolve = (): ToolBase<
    ReturnType<typeof TaskContextWikiChannelResolveSchema>,
    Schemas.ChannelWikiPage
> => ({
    name: 'task-context-wiki-channel-resolve',
    schema: TaskContextWikiChannelResolveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof TaskContextWikiChannelResolveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ChannelWikiPage>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/context_layer/agent/channel-pages/${encodeURIComponent(String(params.channel_id))}/`,
        })
        return result
    },
})

const TaskContextWikiPageRetrieveSchema = () => {
    const ContextLayerAgentPagesRetrieveQueryParams = orvalSchemas.ContextLayerAgentPagesRetrieveQueryParams()
    return ContextLayerAgentPagesRetrieveQueryParams
}

const taskContextWikiPageRetrieve = (): ToolBase<
    ReturnType<typeof TaskContextWikiPageRetrieveSchema>,
    Schemas.WikiPage
> => ({
    name: 'task-context-wiki-page-retrieve',
    schema: TaskContextWikiPageRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof TaskContextWikiPageRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.WikiPage>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/context_layer/agent/pages/`,
            query: {
                path: params.path,
            },
        })
        return result
    },
})

const TaskContextWikiPageUpdateSchema = () => {
    const ContextLayerAgentPagesUpdateBody = orvalSchemas.ContextLayerAgentPagesUpdateBody()
    return ContextLayerAgentPagesUpdateBody
}

const taskContextWikiPageUpdate = (): ToolBase<
    ReturnType<typeof TaskContextWikiPageUpdateSchema>,
    Schemas.ContextLayerStatus
> => ({
    name: 'task-context-wiki-page-update',
    schema: TaskContextWikiPageUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof TaskContextWikiPageUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.path !== undefined) {
            body['path'] = params.path
        }
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        if (params.base_head !== undefined) {
            body['base_head'] = params.base_head
        }
        const result = await context.api.request<Schemas.ContextLayerStatus>({
            method: 'PUT',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/context_layer/agent/pages/`,
            body,
        })
        return result
    },
})

const LoopContextWikiChannelResolveSchema = () => {
    const ContextLayerAgentChannelPagesRetrieveParams = orvalSchemas.ContextLayerAgentChannelPagesRetrieveParams()
    return ContextLayerAgentChannelPagesRetrieveParams.omit({ project_id: true })
}

const loopContextWikiChannelResolve = (): ToolBase<
    ReturnType<typeof LoopContextWikiChannelResolveSchema>,
    Schemas.ChannelWikiPage
> => ({
    name: 'loop-context-wiki-channel-resolve',
    schema: LoopContextWikiChannelResolveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof LoopContextWikiChannelResolveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ChannelWikiPage>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/context_layer/agent/channel-pages/${encodeURIComponent(String(params.channel_id))}/`,
        })
        return result
    },
})

const LoopContextWikiPageRetrieveSchema = () => {
    const ContextLayerAgentPagesRetrieveQueryParams = orvalSchemas.ContextLayerAgentPagesRetrieveQueryParams()
    return ContextLayerAgentPagesRetrieveQueryParams
}

const loopContextWikiPageRetrieve = (): ToolBase<
    ReturnType<typeof LoopContextWikiPageRetrieveSchema>,
    Schemas.WikiPage
> => ({
    name: 'loop-context-wiki-page-retrieve',
    schema: LoopContextWikiPageRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof LoopContextWikiPageRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.WikiPage>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/context_layer/agent/pages/`,
            query: {
                path: params.path,
            },
        })
        return result
    },
})

const LoopContextWikiPageUpdateSchema = () => {
    const ContextLayerAgentPagesUpdateBody = orvalSchemas.ContextLayerAgentPagesUpdateBody()
    return ContextLayerAgentPagesUpdateBody
}

const loopContextWikiPageUpdate = (): ToolBase<
    ReturnType<typeof LoopContextWikiPageUpdateSchema>,
    Schemas.ContextLayerStatus
> => ({
    name: 'loop-context-wiki-page-update',
    schema: LoopContextWikiPageUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof LoopContextWikiPageUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.path !== undefined) {
            body['path'] = params.path
        }
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        if (params.base_head !== undefined) {
            body['base_head'] = params.base_head
        }
        const result = await context.api.request<Schemas.ContextLayerStatus>({
            method: 'PUT',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/context_layer/agent/pages/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'context-wiki-channel-resolve': contextWikiChannelResolve,
    'context-wiki-page-retrieve': contextWikiPageRetrieve,
    'context-wiki-page-update': contextWikiPageUpdate,
    'task-context-wiki-channel-resolve': taskContextWikiChannelResolve,
    'task-context-wiki-page-retrieve': taskContextWikiPageRetrieve,
    'task-context-wiki-page-update': taskContextWikiPageUpdate,
    'loop-context-wiki-channel-resolve': loopContextWikiChannelResolve,
    'loop-context-wiki-page-retrieve': loopContextWikiPageRetrieve,
    'loop-context-wiki-page-update': loopContextWikiPageUpdate,
}
