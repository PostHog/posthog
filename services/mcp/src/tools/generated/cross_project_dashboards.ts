// AUTO-GENERATED from products/cross_project_dashboards/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/cross_project_dashboards/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const CrossProjectDashboardsListSchema = () => {
    const CrossProjectDashboardsListQueryParams = orvalSchemas.CrossProjectDashboardsListQueryParams()
    return CrossProjectDashboardsListQueryParams
}

const crossProjectDashboardsList = (): ToolBase<
    ReturnType<typeof CrossProjectDashboardsListSchema>,
    WithPostHogUrl<Schemas.PaginatedCrossProjectDashboardList>
> => ({
    name: 'cross-project-dashboards-list',
    schema: CrossProjectDashboardsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CrossProjectDashboardsListSchema>>) => {
        const orgId = await context.stateManager.getOrgID()
        const result = await context.api.request<Schemas.PaginatedCrossProjectDashboardList>({
            method: 'GET',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/cross_project_dashboards/`,
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
                        withPostHogUrl(context, item, `/cross-project-dashboards/${item.id}`)
                    )
                ),
            },
            '/cross-project-dashboards'
        )
    },
})

const CrossProjectDashboardsGetSchema = () => {
    const CrossProjectDashboardsRetrieveParams = orvalSchemas.CrossProjectDashboardsRetrieveParams()
    return CrossProjectDashboardsRetrieveParams.omit({ organization_id: true })
}

const crossProjectDashboardsGet = (): ToolBase<
    ReturnType<typeof CrossProjectDashboardsGetSchema>,
    WithPostHogUrl<Schemas.CrossProjectDashboard>
> => ({
    name: 'cross-project-dashboards-get',
    schema: CrossProjectDashboardsGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CrossProjectDashboardsGetSchema>>) => {
        const orgId = await context.stateManager.getOrgID()
        const result = await context.api.request<Schemas.CrossProjectDashboard>({
            method: 'GET',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/cross_project_dashboards/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/cross-project-dashboards/${result.id}`)
    },
})

const CrossProjectDashboardTilesListSchema = () => {
    const CrossProjectDashboardsTilesListParams = orvalSchemas.CrossProjectDashboardsTilesListParams()
    const CrossProjectDashboardsTilesListQueryParams = orvalSchemas.CrossProjectDashboardsTilesListQueryParams()
    return CrossProjectDashboardsTilesListParams.omit({ organization_id: true }).extend(
        CrossProjectDashboardsTilesListQueryParams.shape
    )
}

const crossProjectDashboardTilesList = (): ToolBase<
    ReturnType<typeof CrossProjectDashboardTilesListSchema>,
    WithPostHogUrl<Schemas.PaginatedCrossProjectDashboardTileList>
> => ({
    name: 'cross-project-dashboard-tiles-list',
    schema: CrossProjectDashboardTilesListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CrossProjectDashboardTilesListSchema>>) => {
        const orgId = await context.stateManager.getOrgID()
        const result = await context.api.request<Schemas.PaginatedCrossProjectDashboardTileList>({
            method: 'GET',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/cross_project_dashboards/${encodeURIComponent(String(params.dashboard_id))}/tiles/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/cross-project-dashboards')
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'cross-project-dashboards-list': crossProjectDashboardsList,
    'cross-project-dashboards-get': crossProjectDashboardsGet,
    'cross-project-dashboard-tiles-list': crossProjectDashboardTilesList,
}
