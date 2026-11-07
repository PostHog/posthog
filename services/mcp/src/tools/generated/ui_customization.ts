// AUTO-GENERATED from products/ui_customization/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/ui_customization/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const UiCustomizationAnalyticsSidebarGetSchema = () => z.object({})

const uiCustomizationAnalyticsSidebarGet = (): ToolBase<
    ReturnType<typeof UiCustomizationAnalyticsSidebarGetSchema>,
    Schemas.AnalyticsSidebar
> => ({
    name: 'ui-customization-analytics-sidebar-get',
    schema: UiCustomizationAnalyticsSidebarGetSchema(),
    handler: async (
        context: Context,
        _params: z.infer<ReturnType<typeof UiCustomizationAnalyticsSidebarGetSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AnalyticsSidebar>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/ui_customization/analytics_sidebar/`,
        })
        return result
    },
})

const UiCustomizationAnalyticsSidebarResetSchema = () => z.object({})

const uiCustomizationAnalyticsSidebarReset = (): ToolBase<
    ReturnType<typeof UiCustomizationAnalyticsSidebarResetSchema>,
    Schemas.AnalyticsSidebar
> => ({
    name: 'ui-customization-analytics-sidebar-reset',
    schema: UiCustomizationAnalyticsSidebarResetSchema(),
    handler: async (
        context: Context,
        _params: z.infer<ReturnType<typeof UiCustomizationAnalyticsSidebarResetSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AnalyticsSidebar>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/ui_customization/analytics_sidebar/`,
        })
        return result
    },
})

const UiCustomizationAnalyticsSidebarUpdateSchema = () => {
    const UiCustomizationAnalyticsSidebarUpdateBody = orvalSchemas.UiCustomizationAnalyticsSidebarUpdateBody()
    return UiCustomizationAnalyticsSidebarUpdateBody
}

const uiCustomizationAnalyticsSidebarUpdate = (): ToolBase<
    ReturnType<typeof UiCustomizationAnalyticsSidebarUpdateSchema>,
    Schemas.AnalyticsSidebar
> => ({
    name: 'ui-customization-analytics-sidebar-update',
    schema: UiCustomizationAnalyticsSidebarUpdateSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof UiCustomizationAnalyticsSidebarUpdateSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.layout !== undefined) {
            body['layout'] = params.layout
        }
        const result = await context.api.request<Schemas.AnalyticsSidebar>({
            method: 'PUT',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/ui_customization/analytics_sidebar/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'ui-customization-analytics-sidebar-get': uiCustomizationAnalyticsSidebarGet,
    'ui-customization-analytics-sidebar-reset': uiCustomizationAnalyticsSidebarReset,
    'ui-customization-analytics-sidebar-update': uiCustomizationAnalyticsSidebarUpdate,
}
