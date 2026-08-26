// AUTO-GENERATED from products/streamlit_apps/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    StreamlitAppsCreateBody,
    StreamlitAppsCreateVersionFromSourceCreateBody,
    StreamlitAppsCreateVersionFromSourceCreateParams,
    StreamlitAppsDestroyParams,
    StreamlitAppsListQueryParams,
    StreamlitAppsPartialUpdateBody,
    StreamlitAppsPartialUpdateParams,
    StreamlitAppsRetrieveParams,
    StreamlitAppsStartCreateParams,
    StreamlitAppsStatusRetrieveParams,
    StreamlitAppsStopCreateParams,
    StreamlitAppsVersionsRetrieveParams,
} from '@/generated/streamlit_apps/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const StreamlitAppsCreateSchema = StreamlitAppsCreateBody

const streamlitAppsCreate = (): ToolBase<typeof StreamlitAppsCreateSchema, WithPostHogUrl<Schemas.AppContract>> => ({
    name: 'streamlit-apps-create',
    schema: StreamlitAppsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof StreamlitAppsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.cpu_cores !== undefined) {
            body['cpu_cores'] = params.cpu_cores
        }
        if (params.memory_gb !== undefined) {
            body['memory_gb'] = params.memory_gb
        }
        const result = await context.api.request<Schemas.AppContract>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/streamlit_apps/`,
            body,
        })
        return await withPostHogUrl(context, result, `/streamlit-apps/${result.short_id}`)
    },
})

const StreamlitAppsDeleteSchema = StreamlitAppsDestroyParams.omit({ project_id: true })

const streamlitAppsDelete = (): ToolBase<typeof StreamlitAppsDeleteSchema, unknown> => ({
    name: 'streamlit-apps-delete',
    schema: StreamlitAppsDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof StreamlitAppsDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/streamlit_apps/${encodeURIComponent(String(params.short_id))}/`,
        })
        return result
    },
})

const StreamlitAppsGetSchema = StreamlitAppsRetrieveParams.omit({ project_id: true })

const streamlitAppsGet = (): ToolBase<typeof StreamlitAppsGetSchema, WithPostHogUrl<Schemas.AppContract>> => ({
    name: 'streamlit-apps-get',
    schema: StreamlitAppsGetSchema,
    handler: async (context: Context, params: z.infer<typeof StreamlitAppsGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AppContract>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/streamlit_apps/${encodeURIComponent(String(params.short_id))}/`,
        })
        return await withPostHogUrl(context, result, `/streamlit-apps/${result.short_id}`)
    },
})

const StreamlitAppsListSchema = StreamlitAppsListQueryParams

const streamlitAppsList = (): ToolBase<
    typeof StreamlitAppsListSchema,
    WithPostHogUrl<Schemas.PaginatedAppSummaryContractList>
> => ({
    name: 'streamlit-apps-list',
    schema: StreamlitAppsListSchema,
    handler: async (context: Context, params: z.infer<typeof StreamlitAppsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAppSummaryContractList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/streamlit_apps/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(
            context,
            {
                ...result,
                results: await Promise.all(
                    (result.results ?? []).map((item) =>
                        withPostHogUrl(context, item, `/streamlit-apps/${item.short_id}`)
                    )
                ),
            },
            '/streamlit-apps'
        )
    },
})

const StreamlitAppsSetSourceSchema = StreamlitAppsCreateVersionFromSourceCreateParams.omit({ project_id: true })
    .extend(StreamlitAppsCreateVersionFromSourceCreateBody.shape)
    .extend({
        source: StreamlitAppsCreateVersionFromSourceCreateBody.shape['source'].describe(
            "The complete Python source for the app's root app.py (a Streamlit script, e.g. starting with `import streamlit as st`). Sent as plain text."
        ),
    })

const streamlitAppsSetSource = (): ToolBase<typeof StreamlitAppsSetSourceSchema, Schemas.AppVersionContract> => ({
    name: 'streamlit-apps-set-source',
    schema: StreamlitAppsSetSourceSchema,
    handler: async (context: Context, params: z.infer<typeof StreamlitAppsSetSourceSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.source !== undefined) {
            body['source'] = params.source
        }
        const result = await context.api.request<Schemas.AppVersionContract>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/streamlit_apps/${encodeURIComponent(String(params.short_id))}/create_version_from_source/`,
            body,
        })
        return result
    },
})

const StreamlitAppsStartSchema = StreamlitAppsStartCreateParams.omit({ project_id: true })

const streamlitAppsStart = (): ToolBase<typeof StreamlitAppsStartSchema, WithPostHogUrl<Schemas.AppContract>> => ({
    name: 'streamlit-apps-start',
    schema: StreamlitAppsStartSchema,
    handler: async (context: Context, params: z.infer<typeof StreamlitAppsStartSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AppContract>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/streamlit_apps/${encodeURIComponent(String(params.short_id))}/start/`,
        })
        return await withPostHogUrl(context, result, `/streamlit-apps/${result.short_id}`)
    },
})

const StreamlitAppsStatusSchema = StreamlitAppsStatusRetrieveParams.omit({ project_id: true })

const streamlitAppsStatus = (): ToolBase<typeof StreamlitAppsStatusSchema, Schemas.StreamlitAppStatus> => ({
    name: 'streamlit-apps-status',
    schema: StreamlitAppsStatusSchema,
    handler: async (context: Context, params: z.infer<typeof StreamlitAppsStatusSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.StreamlitAppStatus>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/streamlit_apps/${encodeURIComponent(String(params.short_id))}/status/`,
        })
        return result
    },
})

const StreamlitAppsStopSchema = StreamlitAppsStopCreateParams.omit({ project_id: true })

const streamlitAppsStop = (): ToolBase<typeof StreamlitAppsStopSchema, WithPostHogUrl<Schemas.AppContract>> => ({
    name: 'streamlit-apps-stop',
    schema: StreamlitAppsStopSchema,
    handler: async (context: Context, params: z.infer<typeof StreamlitAppsStopSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AppContract>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/streamlit_apps/${encodeURIComponent(String(params.short_id))}/stop/`,
        })
        return await withPostHogUrl(context, result, `/streamlit-apps/${result.short_id}`)
    },
})

const StreamlitAppsUpdateSchema = StreamlitAppsPartialUpdateParams.omit({ project_id: true }).extend(
    StreamlitAppsPartialUpdateBody.shape
)

const streamlitAppsUpdate = (): ToolBase<typeof StreamlitAppsUpdateSchema, WithPostHogUrl<Schemas.AppContract>> => ({
    name: 'streamlit-apps-update',
    schema: StreamlitAppsUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof StreamlitAppsUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.cpu_cores !== undefined) {
            body['cpu_cores'] = params.cpu_cores
        }
        if (params.memory_gb !== undefined) {
            body['memory_gb'] = params.memory_gb
        }
        const result = await context.api.request<Schemas.AppContract>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/streamlit_apps/${encodeURIComponent(String(params.short_id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/streamlit-apps/${result.short_id}`)
    },
})

const StreamlitAppsVersionsSchema = StreamlitAppsVersionsRetrieveParams.omit({ project_id: true })

const streamlitAppsVersions = (): ToolBase<
    typeof StreamlitAppsVersionsSchema,
    WithPostHogUrl<Schemas.StreamlitAppVersionList>
> => ({
    name: 'streamlit-apps-versions',
    schema: StreamlitAppsVersionsSchema,
    handler: async (context: Context, params: z.infer<typeof StreamlitAppsVersionsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.StreamlitAppVersionList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/streamlit_apps/${encodeURIComponent(String(params.short_id))}/versions/`,
        })
        return await withPostHogUrl(context, result, '/streamlit-apps')
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'streamlit-apps-create': streamlitAppsCreate,
    'streamlit-apps-delete': streamlitAppsDelete,
    'streamlit-apps-get': streamlitAppsGet,
    'streamlit-apps-list': streamlitAppsList,
    'streamlit-apps-set-source': streamlitAppsSetSource,
    'streamlit-apps-start': streamlitAppsStart,
    'streamlit-apps-status': streamlitAppsStatus,
    'streamlit-apps-stop': streamlitAppsStop,
    'streamlit-apps-update': streamlitAppsUpdate,
    'streamlit-apps-versions': streamlitAppsVersions,
}
