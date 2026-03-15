// AUTO-GENERATED from products/dashboards/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    DashboardsCreateBody,
    DashboardsDestroyParams,
    DashboardsListQueryParams,
    DashboardsPartialUpdateBody,
    DashboardsPartialUpdateParams,
    DashboardsReorderTilesCreateBody,
    DashboardsReorderTilesCreateParams,
    DashboardsRetrieveParams,
} from '@/generated/dashboards/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const DashboardsGetAllSchema = DashboardsListQueryParams.omit({ format: true })

const dashboardsGetAll = (): ToolBase<typeof DashboardsGetAllSchema, unknown> => ({
    name: 'dashboards-get-all',
    schema: DashboardsGetAllSchema,
    handler: async (context: Context, params: z.infer<typeof DashboardsGetAllSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedDashboardBasicList>({
            method: 'GET',
            path: `/api/projects/${projectId}/dashboards/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const items = (result as any).results ?? result
        return {
            ...(result as any),
            results: (items as any[]).map((item: any) => ({
                ...item,
                _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/dashboard/${item.id}`,
            })),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/dashboard`,
        }
    },
})

const DashboardCreateSchema = DashboardsCreateBody

const dashboardCreate = (): ToolBase<typeof DashboardCreateSchema, Schemas.Dashboard & { _posthogUrl: string }> => ({
    name: 'dashboard-create',
    schema: DashboardCreateSchema,
    handler: async (context: Context, params: z.infer<typeof DashboardCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.pinned !== undefined) {
            body['pinned'] = params.pinned
        }
        if (params.breakdown_colors !== undefined) {
            body['breakdown_colors'] = params.breakdown_colors
        }
        if (params.data_color_theme_id !== undefined) {
            body['data_color_theme_id'] = params.data_color_theme_id
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.restriction_level !== undefined) {
            body['restriction_level'] = params.restriction_level
        }
        if (params.quick_filter_ids !== undefined) {
            body['quick_filter_ids'] = params.quick_filter_ids
        }
        if (params.use_template !== undefined) {
            body['use_template'] = params.use_template
        }
        if (params.use_dashboard !== undefined) {
            body['use_dashboard'] = params.use_dashboard
        }
        if (params.delete_insights !== undefined) {
            body['delete_insights'] = params.delete_insights
        }
        const result = await context.api.request<Schemas.Dashboard>({
            method: 'POST',
            path: `/api/projects/${projectId}/dashboards/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/dashboard/${(result as any).id}`,
        }
    },
})

const DashboardGetSchema = DashboardsRetrieveParams.omit({ project_id: true })

const dashboardGet = (): ToolBase<typeof DashboardGetSchema, Schemas.Dashboard & { _posthogUrl: string }> => ({
    name: 'dashboard-get',
    schema: DashboardGetSchema,
    handler: async (context: Context, params: z.infer<typeof DashboardGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Dashboard>({
            method: 'GET',
            path: `/api/projects/${projectId}/dashboards/${params.id}/`,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/dashboard/${(result as any).id}`,
        }
    },
})

const DashboardUpdateSchema = DashboardsPartialUpdateParams.omit({ project_id: true }).extend(
    DashboardsPartialUpdateBody.shape
)

const dashboardUpdate = (): ToolBase<typeof DashboardUpdateSchema, Schemas.Dashboard & { _posthogUrl: string }> => ({
    name: 'dashboard-update',
    schema: DashboardUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof DashboardUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.pinned !== undefined) {
            body['pinned'] = params.pinned
        }
        if (params.breakdown_colors !== undefined) {
            body['breakdown_colors'] = params.breakdown_colors
        }
        if (params.data_color_theme_id !== undefined) {
            body['data_color_theme_id'] = params.data_color_theme_id
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.restriction_level !== undefined) {
            body['restriction_level'] = params.restriction_level
        }
        if (params.quick_filter_ids !== undefined) {
            body['quick_filter_ids'] = params.quick_filter_ids
        }
        if (params.use_template !== undefined) {
            body['use_template'] = params.use_template
        }
        if (params.use_dashboard !== undefined) {
            body['use_dashboard'] = params.use_dashboard
        }
        if (params.delete_insights !== undefined) {
            body['delete_insights'] = params.delete_insights
        }
        const result = await context.api.request<Schemas.Dashboard>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/dashboards/${params.id}/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/dashboard/${(result as any).id}`,
        }
    },
})

const DashboardDeleteSchema = DashboardsDestroyParams.omit({ project_id: true })

const dashboardDelete = (): ToolBase<typeof DashboardDeleteSchema, unknown> => ({
    name: 'dashboard-delete',
    schema: DashboardDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof DashboardDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/dashboards/${params.id}/`,
            body: { deleted: true },
        })
        return result
    },
})

const DashboardReorderTilesSchema = DashboardsReorderTilesCreateParams.omit({ project_id: true }).extend(
    DashboardsReorderTilesCreateBody.shape
)

const dashboardReorderTiles = (): ToolBase<
    typeof DashboardReorderTilesSchema,
    Schemas.Dashboard & { _posthogUrl: string }
> => ({
    name: 'dashboard-reorder-tiles',
    schema: DashboardReorderTilesSchema,
    handler: async (context: Context, params: z.infer<typeof DashboardReorderTilesSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.tile_order !== undefined) {
            body['tile_order'] = params.tile_order
        }
        const result = await context.api.request<Schemas.Dashboard>({
            method: 'POST',
            path: `/api/projects/${projectId}/dashboards/${params.id}/reorder_tiles/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/dashboard/${(result as any).id}`,
        }
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'dashboards-get-all': dashboardsGetAll,
    'dashboard-create': dashboardCreate,
    'dashboard-get': dashboardGet,
    'dashboard-update': dashboardUpdate,
    'dashboard-delete': dashboardDelete,
    'dashboard-reorder-tiles': dashboardReorderTiles,
}
