// AUTO-GENERATED from products/replay/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    SessionRecordingPlaylistsCreateBody,
    SessionRecordingPlaylistsListQueryParams,
    SessionRecordingPlaylistsPartialUpdateBody,
    SessionRecordingPlaylistsPartialUpdateParams,
    SessionRecordingPlaylistsRetrieveParams,
    SessionRecordingsDestroyParams,
    SessionRecordingsListQueryParams,
    SessionRecordingsRetrieveParams,
} from '@/generated/replay/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const SessionRecordingsListSchema = SessionRecordingsListQueryParams

const sessionRecordingsList = (): ToolBase<
    typeof SessionRecordingsListSchema,
    WithPostHogUrl<Schemas.PaginatedSessionRecordingList>
> => ({
    name: 'session-recordings-list',
    schema: SessionRecordingsListSchema,
    handler: async (context: Context, params: z.infer<typeof SessionRecordingsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedSessionRecordingList>({
            method: 'GET',
            path: `/api/projects/${projectId}/session_recordings/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/replay')
    },
})

const SessionRecordingGetSchema = SessionRecordingsRetrieveParams.omit({ project_id: true })

const sessionRecordingGet = (): ToolBase<typeof SessionRecordingGetSchema, Schemas.SessionRecording> => ({
    name: 'session-recording-get',
    schema: SessionRecordingGetSchema,
    handler: async (context: Context, params: z.infer<typeof SessionRecordingGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SessionRecording>({
            method: 'GET',
            path: `/api/projects/${projectId}/session_recordings/${params.id}/`,
        })
        return result
    },
})

const SessionRecordingDeleteSchema = SessionRecordingsDestroyParams.omit({ project_id: true })

const sessionRecordingDelete = (): ToolBase<typeof SessionRecordingDeleteSchema, unknown> => ({
    name: 'session-recording-delete',
    schema: SessionRecordingDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof SessionRecordingDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${projectId}/session_recordings/${params.id}/`,
        })
        return result
    },
})

const SessionRecordingPlaylistsListSchema = SessionRecordingPlaylistsListQueryParams

const sessionRecordingPlaylistsList = (): ToolBase<
    typeof SessionRecordingPlaylistsListSchema,
    WithPostHogUrl<Schemas.PaginatedSessionRecordingPlaylistList>
> => ({
    name: 'session-recording-playlists-list',
    schema: SessionRecordingPlaylistsListSchema,
    handler: async (context: Context, params: z.infer<typeof SessionRecordingPlaylistsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedSessionRecordingPlaylistList>({
            method: 'GET',
            path: `/api/projects/${projectId}/session_recording_playlists/`,
            query: {
                created_by: params.created_by,
                limit: params.limit,
                offset: params.offset,
                short_id: params.short_id,
            },
        })
        return await withPostHogUrl(context, result, '/replay')
    },
})

const SessionRecordingPlaylistGetSchema = SessionRecordingPlaylistsRetrieveParams.omit({ project_id: true })

const sessionRecordingPlaylistGet = (): ToolBase<
    typeof SessionRecordingPlaylistGetSchema,
    Schemas.SessionRecordingPlaylist
> => ({
    name: 'session-recording-playlist-get',
    schema: SessionRecordingPlaylistGetSchema,
    handler: async (context: Context, params: z.infer<typeof SessionRecordingPlaylistGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SessionRecordingPlaylist>({
            method: 'GET',
            path: `/api/projects/${projectId}/session_recording_playlists/${params.short_id}/`,
        })
        return result
    },
})

const SessionRecordingPlaylistCreateSchema = SessionRecordingPlaylistsCreateBody

const sessionRecordingPlaylistCreate = (): ToolBase<
    typeof SessionRecordingPlaylistCreateSchema,
    Schemas.SessionRecordingPlaylist
> => ({
    name: 'session-recording-playlist-create',
    schema: SessionRecordingPlaylistCreateSchema,
    handler: async (context: Context, params: z.infer<typeof SessionRecordingPlaylistCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.derived_name !== undefined) {
            body['derived_name'] = params.derived_name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.pinned !== undefined) {
            body['pinned'] = params.pinned
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        const result = await context.api.request<Schemas.SessionRecordingPlaylist>({
            method: 'POST',
            path: `/api/projects/${projectId}/session_recording_playlists/`,
            body,
        })
        return result
    },
})

const SessionRecordingPlaylistUpdateSchema = SessionRecordingPlaylistsPartialUpdateParams.omit({
    project_id: true,
}).extend(SessionRecordingPlaylistsPartialUpdateBody.shape)

const sessionRecordingPlaylistUpdate = (): ToolBase<
    typeof SessionRecordingPlaylistUpdateSchema,
    Schemas.SessionRecordingPlaylist
> => ({
    name: 'session-recording-playlist-update',
    schema: SessionRecordingPlaylistUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof SessionRecordingPlaylistUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.derived_name !== undefined) {
            body['derived_name'] = params.derived_name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.pinned !== undefined) {
            body['pinned'] = params.pinned
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        const result = await context.api.request<Schemas.SessionRecordingPlaylist>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/session_recording_playlists/${params.short_id}/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'session-recordings-list': sessionRecordingsList,
    'session-recording-get': sessionRecordingGet,
    'session-recording-delete': sessionRecordingDelete,
    'session-recording-playlists-list': sessionRecordingPlaylistsList,
    'session-recording-playlist-get': sessionRecordingPlaylistGet,
    'session-recording-playlist-create': sessionRecordingPlaylistCreate,
    'session-recording-playlist-update': sessionRecordingPlaylistUpdate,
}
