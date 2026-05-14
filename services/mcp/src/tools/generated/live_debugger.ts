// AUTO-GENERATED from products/live_debugger/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    LiveDebuggerSessionsCloseCreateBody,
    LiveDebuggerSessionsCloseCreateParams,
    LiveDebuggerSessionsCreateBody,
    LiveDebuggerSessionsEntriesCreateBody,
    LiveDebuggerSessionsEntriesCreateParams,
    LiveDebuggerSessionsInstallProgramCreateBody,
    LiveDebuggerSessionsInstallProgramCreateParams,
    LiveDebuggerSessionsListQueryParams,
    LiveDebuggerSessionsProgramEventsRetrieveParams,
    LiveDebuggerSessionsProgramEventsRetrieveQueryParams,
    LiveDebuggerSessionsRetrieveParams,
    LiveDebuggerSessionsUninstallProgramCreateBody,
    LiveDebuggerSessionsUninstallProgramCreateParams,
} from '@/generated/live_debugger/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const DebuggingSessionAddEntrySchema = LiveDebuggerSessionsEntriesCreateParams.omit({ project_id: true }).extend(
    LiveDebuggerSessionsEntriesCreateBody.shape
)

const debuggingSessionAddEntry = (): ToolBase<
    typeof DebuggingSessionAddEntrySchema,
    Schemas.LiveDebuggerSessionEntryListItem
> => ({
    name: 'debugging-session-add-entry',
    schema: DebuggingSessionAddEntrySchema,
    handler: async (context: Context, params: z.infer<typeof DebuggingSessionAddEntrySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.kind !== undefined) {
            body['kind'] = params.kind
        }
        if (params.payload !== undefined) {
            body['payload'] = params.payload
        }
        const result = await context.api.request<Schemas.LiveDebuggerSessionEntryListItem>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/live_debugger_sessions/${encodeURIComponent(String(params.id))}/entries/`,
            body,
        })
        return result
    },
})

const DebuggingSessionCloseSchema = LiveDebuggerSessionsCloseCreateParams.omit({ project_id: true }).extend(
    LiveDebuggerSessionsCloseCreateBody.shape
)

const debuggingSessionClose = (): ToolBase<typeof DebuggingSessionCloseSchema, Schemas.LiveDebuggerSession> => ({
    name: 'debugging-session-close',
    schema: DebuggingSessionCloseSchema,
    handler: async (context: Context, params: z.infer<typeof DebuggingSessionCloseSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.conclusion_markdown !== undefined) {
            body['conclusion_markdown'] = params.conclusion_markdown
        }
        const result = await context.api.request<Schemas.LiveDebuggerSession>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/live_debugger_sessions/${encodeURIComponent(String(params.id))}/close/`,
            body,
        })
        return result
    },
})

const DebuggingSessionInstallProgramSchema = LiveDebuggerSessionsInstallProgramCreateParams.omit({
    project_id: true,
}).extend(LiveDebuggerSessionsInstallProgramCreateBody.shape)

const debuggingSessionInstallProgram = (): ToolBase<
    typeof DebuggingSessionInstallProgramSchema,
    Schemas.LiveDebuggerProgram
> => ({
    name: 'debugging-session-install-program',
    schema: DebuggingSessionInstallProgramSchema,
    handler: async (context: Context, params: z.infer<typeof DebuggingSessionInstallProgramSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.code !== undefined) {
            body['code'] = params.code
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        const result = await context.api.request<Schemas.LiveDebuggerProgram>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/live_debugger_sessions/${encodeURIComponent(String(params.id))}/install_program/`,
            body,
        })
        return result
    },
})

const DebuggingSessionListSchema = LiveDebuggerSessionsListQueryParams

const debuggingSessionList = (): ToolBase<
    typeof DebuggingSessionListSchema,
    WithPostHogUrl<Schemas.PaginatedLiveDebuggerSessionListItemList>
> => ({
    name: 'debugging-session-list',
    schema: DebuggingSessionListSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof DebuggingSessionListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedLiveDebuggerSessionListItemList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/live_debugger_sessions/`,
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
                        withPostHogUrl(context, item, `/live-debugger/sessions/${item.id}`)
                    )
                ),
            },
            '/live-debugger'
        )
    },
})

const DebuggingSessionProgramEventsSchema = LiveDebuggerSessionsProgramEventsRetrieveParams.omit({
    project_id: true,
}).extend(LiveDebuggerSessionsProgramEventsRetrieveQueryParams.shape)

const debuggingSessionProgramEvents = (): ToolBase<
    typeof DebuggingSessionProgramEventsSchema,
    Schemas.ProgramEventsResponse
> => ({
    name: 'debugging-session-program-events',
    schema: DebuggingSessionProgramEventsSchema,
    handler: async (context: Context, params: z.infer<typeof DebuggingSessionProgramEventsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ProgramEventsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/live_debugger_sessions/${encodeURIComponent(String(params.id))}/program_events/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                program_id: params.program_id,
            },
        })
        return result
    },
})

const DebuggingSessionShowSchema = LiveDebuggerSessionsRetrieveParams.omit({ project_id: true })

const debuggingSessionShow = (): ToolBase<
    typeof DebuggingSessionShowSchema,
    WithPostHogUrl<Schemas.LiveDebuggerSession>
> => ({
    name: 'debugging-session-show',
    schema: DebuggingSessionShowSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof DebuggingSessionShowSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LiveDebuggerSession>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/live_debugger_sessions/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/live-debugger/sessions/${result.id}`)
    },
})

const DebuggingSessionStartSchema = LiveDebuggerSessionsCreateBody

const debuggingSessionStart = (): ToolBase<typeof DebuggingSessionStartSchema, Schemas.LiveDebuggerSession> => ({
    name: 'debugging-session-start',
    schema: DebuggingSessionStartSchema,
    handler: async (context: Context, params: z.infer<typeof DebuggingSessionStartSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        const result = await context.api.request<Schemas.LiveDebuggerSession>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/live_debugger_sessions/`,
            body,
        })
        return result
    },
})

const DebuggingSessionUninstallProgramSchema = LiveDebuggerSessionsUninstallProgramCreateParams.omit({
    project_id: true,
}).extend(LiveDebuggerSessionsUninstallProgramCreateBody.shape)

const debuggingSessionUninstallProgram = (): ToolBase<
    typeof DebuggingSessionUninstallProgramSchema,
    Schemas.LiveDebuggerProgram
> => ({
    name: 'debugging-session-uninstall-program',
    schema: DebuggingSessionUninstallProgramSchema,
    handler: async (context: Context, params: z.infer<typeof DebuggingSessionUninstallProgramSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.program_id !== undefined) {
            body['program_id'] = params.program_id
        }
        const result = await context.api.request<Schemas.LiveDebuggerProgram>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/live_debugger_sessions/${encodeURIComponent(String(params.id))}/uninstall_program/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'debugging-session-add-entry': debuggingSessionAddEntry,
    'debugging-session-close': debuggingSessionClose,
    'debugging-session-install-program': debuggingSessionInstallProgram,
    'debugging-session-list': debuggingSessionList,
    'debugging-session-program-events': debuggingSessionProgramEvents,
    'debugging-session-show': debuggingSessionShow,
    'debugging-session-start': debuggingSessionStart,
    'debugging-session-uninstall-program': debuggingSessionUninstallProgram,
}
