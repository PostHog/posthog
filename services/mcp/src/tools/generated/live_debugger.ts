// AUTO-GENERATED from products/live_debugger/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    LiveDebuggerProgramsCreateBody,
    LiveDebuggerProgramsEventsRetrieveParams,
    LiveDebuggerProgramsEventsRetrieveQueryParams,
    LiveDebuggerProgramsListQueryParams,
    LiveDebuggerProgramsRetrieveParams,
    LiveDebuggerProgramsUninstallCreateParams,
} from '@/generated/live_debugger/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const LiveDebuggerProgramsInstallSchema = LiveDebuggerProgramsCreateBody

const liveDebuggerProgramsInstall = (): ToolBase<
    typeof LiveDebuggerProgramsInstallSchema,
    Schemas.LiveDebuggerProgram
> => ({
    name: 'live-debugger-programs-install',
    schema: LiveDebuggerProgramsInstallSchema,
    handler: async (context: Context, params: z.infer<typeof LiveDebuggerProgramsInstallSchema>) => {
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/live_debugger_programs/`,
            body,
        })
        return result
    },
})

const LiveDebuggerProgramsUninstallSchema = LiveDebuggerProgramsUninstallCreateParams.omit({ project_id: true })

const liveDebuggerProgramsUninstall = (): ToolBase<
    typeof LiveDebuggerProgramsUninstallSchema,
    Schemas.LiveDebuggerProgram
> => ({
    name: 'live-debugger-programs-uninstall',
    schema: LiveDebuggerProgramsUninstallSchema,
    handler: async (context: Context, params: z.infer<typeof LiveDebuggerProgramsUninstallSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LiveDebuggerProgram>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/live_debugger_programs/${encodeURIComponent(String(params.id))}/uninstall/`,
        })
        return result
    },
})

const LiveDebuggerProgramsListSchema = LiveDebuggerProgramsListQueryParams

const liveDebuggerProgramsList = (): ToolBase<
    typeof LiveDebuggerProgramsListSchema,
    WithPostHogUrl<Schemas.PaginatedLiveDebuggerProgramListItemList>
> => ({
    name: 'live-debugger-programs-list',
    schema: LiveDebuggerProgramsListSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof LiveDebuggerProgramsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedLiveDebuggerProgramListItemList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/live_debugger_programs/`,
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
                    (result.results ?? []).map((item) => withPostHogUrl(context, item, `/live-debugger/${item.id}`))
                ),
            },
            '/live-debugger'
        )
    },
})

const LiveDebuggerProgramsShowSchema = LiveDebuggerProgramsRetrieveParams.omit({ project_id: true })

const liveDebuggerProgramsShow = (): ToolBase<
    typeof LiveDebuggerProgramsShowSchema,
    WithPostHogUrl<Schemas.LiveDebuggerProgram>
> => ({
    name: 'live-debugger-programs-show',
    schema: LiveDebuggerProgramsShowSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof LiveDebuggerProgramsShowSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LiveDebuggerProgram>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/live_debugger_programs/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/live-debugger/${result.id}`)
    },
})

const LiveDebuggerProgramsEventsSchema = LiveDebuggerProgramsEventsRetrieveParams.omit({ project_id: true }).extend(
    LiveDebuggerProgramsEventsRetrieveQueryParams.shape
)

const liveDebuggerProgramsEvents = (): ToolBase<
    typeof LiveDebuggerProgramsEventsSchema,
    Schemas.ProgramEventsResponse
> => ({
    name: 'live-debugger-programs-events',
    schema: LiveDebuggerProgramsEventsSchema,
    handler: async (context: Context, params: z.infer<typeof LiveDebuggerProgramsEventsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ProgramEventsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/live_debugger_programs/${encodeURIComponent(String(params.id))}/events/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'live-debugger-programs-install': liveDebuggerProgramsInstall,
    'live-debugger-programs-uninstall': liveDebuggerProgramsUninstall,
    'live-debugger-programs-list': liveDebuggerProgramsList,
    'live-debugger-programs-show': liveDebuggerProgramsShow,
    'live-debugger-programs-events': liveDebuggerProgramsEvents,
}
