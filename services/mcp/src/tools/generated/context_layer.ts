// AUTO-GENERATED from products/context_layer/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    ContextLayerAgentChannelPagesRetrieveParams,
    ContextLayerAgentPagesRetrieveQueryParams,
    ContextLayerAgentPagesUpdateBody,
    ContextLayerChannelPagesRetrieveParams,
    ContextLayerPagesRetrieveQueryParams,
    ContextLayerPagesUpdateBody,
} from '@/generated/context_layer/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ContextWikiChannelResolveSchema = ContextLayerChannelPagesRetrieveParams.omit({ organization_id: true })

const contextWikiChannelResolve = (): ToolBase<typeof ContextWikiChannelResolveSchema, Schemas.ChannelWikiPage> => ({
    name: 'context-wiki-channel-resolve',
    schema: ContextWikiChannelResolveSchema,
    handler: async (context: Context, params: z.infer<typeof ContextWikiChannelResolveSchema>) => {
        const orgId = await context.stateManager.getOrgID()
        const result = await context.api.request<Schemas.ChannelWikiPage>({
            method: 'GET',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/context_layer/channel-pages/${encodeURIComponent(String(params.channel_id))}/`,
        })
        return result
    },
})

const ContextWikiPageRetrieveSchema = ContextLayerPagesRetrieveQueryParams

const contextWikiPageRetrieve = (): ToolBase<typeof ContextWikiPageRetrieveSchema, Schemas.WikiPage> => ({
    name: 'context-wiki-page-retrieve',
    schema: ContextWikiPageRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof ContextWikiPageRetrieveSchema>) => {
        const orgId = await context.stateManager.getOrgID()
        const result = await context.api.request<Schemas.WikiPage>({
            method: 'GET',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/context_layer/pages/`,
            query: {
                path: params.path,
            },
        })
        return result
    },
})

const ContextWikiPageUpdateSchema = ContextLayerPagesUpdateBody

const contextWikiPageUpdate = (): ToolBase<typeof ContextWikiPageUpdateSchema, Schemas.ContextLayerStatus> => ({
    name: 'context-wiki-page-update',
    schema: ContextWikiPageUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof ContextWikiPageUpdateSchema>) => {
        const orgId = await context.stateManager.getOrgID()
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
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/context_layer/pages/`,
            body,
        })
        return result
    },
})

const LoopContextWikiChannelResolveSchema = ContextLayerAgentChannelPagesRetrieveParams.omit({ project_id: true })

const loopContextWikiChannelResolve = (): ToolBase<
    typeof LoopContextWikiChannelResolveSchema,
    Schemas.ChannelWikiPage
> => ({
    name: 'loop-context-wiki-channel-resolve',
    schema: LoopContextWikiChannelResolveSchema,
    handler: async (context: Context, params: z.infer<typeof LoopContextWikiChannelResolveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ChannelWikiPage>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/context_layer/agent/channel-pages/${encodeURIComponent(String(params.channel_id))}/`,
        })
        return result
    },
})

const LoopContextWikiPageRetrieveSchema = ContextLayerAgentPagesRetrieveQueryParams

const loopContextWikiPageRetrieve = (): ToolBase<typeof LoopContextWikiPageRetrieveSchema, Schemas.WikiPage> => ({
    name: 'loop-context-wiki-page-retrieve',
    schema: LoopContextWikiPageRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof LoopContextWikiPageRetrieveSchema>) => {
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

const LoopContextWikiPageUpdateSchema = ContextLayerAgentPagesUpdateBody

const loopContextWikiPageUpdate = (): ToolBase<typeof LoopContextWikiPageUpdateSchema, Schemas.ContextLayerStatus> => ({
    name: 'loop-context-wiki-page-update',
    schema: LoopContextWikiPageUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof LoopContextWikiPageUpdateSchema>) => {
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
    'loop-context-wiki-channel-resolve': loopContextWikiChannelResolve,
    'loop-context-wiki-page-retrieve': loopContextWikiPageRetrieve,
    'loop-context-wiki-page-update': loopContextWikiPageUpdate,
}
