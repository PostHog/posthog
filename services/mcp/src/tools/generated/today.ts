// AUTO-GENERATED from products/today/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/today/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const TodayAnalyticsSidebarGetSchema = () => z.object({})

const todayAnalyticsSidebarGet = (): ToolBase<
    ReturnType<typeof TodayAnalyticsSidebarGetSchema>,
    Schemas.AnalyticsSidebar
> => ({
    name: 'today-analytics-sidebar-get',
    schema: TodayAnalyticsSidebarGetSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof TodayAnalyticsSidebarGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AnalyticsSidebar>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/today/analytics_sidebar/`,
        })
        return result
    },
})

const TodayAnalyticsSidebarResetSchema = () => z.object({})

const todayAnalyticsSidebarReset = (): ToolBase<
    ReturnType<typeof TodayAnalyticsSidebarResetSchema>,
    Schemas.AnalyticsSidebar
> => ({
    name: 'today-analytics-sidebar-reset',
    schema: TodayAnalyticsSidebarResetSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof TodayAnalyticsSidebarResetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AnalyticsSidebar>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/today/analytics_sidebar/`,
        })
        return result
    },
})

const TodayAnalyticsSidebarUpdateSchema = () => {
    const TodayAnalyticsSidebarUpdateBody = orvalSchemas.TodayAnalyticsSidebarUpdateBody()
    return TodayAnalyticsSidebarUpdateBody
}

const todayAnalyticsSidebarUpdate = (): ToolBase<
    ReturnType<typeof TodayAnalyticsSidebarUpdateSchema>,
    Schemas.AnalyticsSidebar
> => ({
    name: 'today-analytics-sidebar-update',
    schema: TodayAnalyticsSidebarUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof TodayAnalyticsSidebarUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.layout !== undefined) {
            body['layout'] = params.layout
        }
        const result = await context.api.request<Schemas.AnalyticsSidebar>({
            method: 'PUT',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/today/analytics_sidebar/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'today-analytics-sidebar-get': todayAnalyticsSidebarGet,
    'today-analytics-sidebar-reset': todayAnalyticsSidebarReset,
    'today-analytics-sidebar-update': todayAnalyticsSidebarUpdate,
}
