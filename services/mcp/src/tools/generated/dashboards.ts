// AUTO-GENERATED from products/dashboards/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    DashboardsCopyTileCreateBody,
    DashboardsCopyTileCreateParams,
    DashboardsCreateBody,
    DashboardsCreateTextTileCreateBody,
    DashboardsCreateTextTileCreateParams,
    DashboardsDeleteTileBody,
    DashboardsDeleteTileParams,
    DashboardsDestroyParams,
    DashboardsListQueryParams,
    DashboardsMoveTilePartialUpdateBody,
    DashboardsMoveTilePartialUpdateParams,
    DashboardsPartialUpdateBody,
    DashboardsPartialUpdateParams,
    DashboardsReorderTilesCreateBody,
    DashboardsReorderTilesCreateParams,
    DashboardsRetrieveParams,
    DashboardsRetrieveQueryParams,
    DashboardsRunInsightsRetrieveParams,
    DashboardsRunInsightsRetrieveQueryParams,
    DashboardsRunWidgetsRetrieveParams,
    DashboardsRunWidgetsRetrieveQueryParams,
    DashboardsUpdateTextTileCreateBody,
    DashboardsUpdateTextTileCreateParams,
    DashboardsUpdateWidgetsBatchBody,
    DashboardsUpdateWidgetsBatchParams,
    DashboardsWidgetsBatchCreateBody,
    DashboardsWidgetsBatchCreateParams,
} from '@/generated/dashboards/api'
import { castStringToInt } from '@/tools/cast-helpers'
import { withPostHogUrl, omitResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const DashboardCreateSchema = DashboardsCreateBody

const dashboardCreate = (): ToolBase<typeof DashboardCreateSchema, WithPostHogUrl<Schemas.Dashboard>> => ({
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
        if (params.insight_ids !== undefined) {
            body['insight_ids'] = params.insight_ids
        }
        if (params.delete_insights !== undefined) {
            body['delete_insights'] = params.delete_insights
        }
        const result = await context.api.request<Schemas.Dashboard>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/dashboards/`,
            body,
        })
        const filtered = omitResponseFields(result, [
            'effective_restriction_level',
            'effective_privilege_level',
            'user_access_level',
            'access_control_version',
            'restriction_level',
            'creation_mode',
            'deleted',
            'breakdown_colors',
            'data_color_theme_id',
            'quick_filter_ids',
            'tiles.*.color',
            'tiles.*.transparent_background',
            'tiles.*.show_description',
            'tiles.*.button_tile',
            'tiles.*.insight.result',
            'tiles.*.insight.hasMore',
            'tiles.*.insight.columns',
            'tiles.*.insight.hogql',
            'tiles.*.insight.types',
            'tiles.*.insight.query_status',
            'tiles.*.insight.cache_target_age',
            'tiles.*.insight.next_allowed_client_refresh',
            'tiles.*.insight.filters_hash',
            'tiles.*.insight.dashboards',
            'tiles.*.insight.dashboard_tiles',
            'tiles.*.insight.effective_restriction_level',
            'tiles.*.insight.effective_privilege_level',
            'tiles.*.insight.user_access_level',
            'tiles.*.insight.filters',
            'tiles.*.insight.is_sample',
            'tiles.*.insight.saved',
            'tiles.*.insight.order',
            'tiles.*.insight.deleted',
            'tiles.*.insight.alerts',
            'tiles.*.insight.last_viewed_at',
            'tiles.*.insight.timezone',
            'tiles.*.insight.resolved_date_range',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/dashboard/${filtered.id}`)
    },
})

const DashboardCreateTextTileSchema = DashboardsCreateTextTileCreateParams.omit({ project_id: true })
    .extend(DashboardsCreateTextTileCreateBody.shape)
    .extend({ id: z.preprocess(castStringToInt, DashboardsCreateTextTileCreateParams.shape['id']) })

const dashboardCreateTextTile = (): ToolBase<
    typeof DashboardCreateTextTileSchema,
    WithPostHogUrl<Schemas.DashboardTile>
> => ({
    name: 'dashboard-create-text-tile',
    schema: DashboardCreateTextTileSchema,
    handler: async (context: Context, params: z.infer<typeof DashboardCreateTextTileSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.body !== undefined) {
            body['body'] = params.body
        }
        if (params.layouts !== undefined) {
            body['layouts'] = params.layouts
        }
        if (params.color !== undefined) {
            body['color'] = params.color
        }
        const result = await context.api.request<Schemas.DashboardTile>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/dashboards/${encodeURIComponent(String(params.id))}/create_text_tile/`,
            body,
        })
        return await withPostHogUrl(context, result, `/dashboard/${params.id}`)
    },
})

const DashboardDeleteSchema = DashboardsDestroyParams.omit({ project_id: true }).extend({
    id: z.preprocess(castStringToInt, DashboardsDestroyParams.shape['id']),
})

const dashboardDelete = (): ToolBase<typeof DashboardDeleteSchema, Schemas.Dashboard> => ({
    name: 'dashboard-delete',
    schema: DashboardDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof DashboardDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Dashboard>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/dashboards/${encodeURIComponent(String(params.id))}/`,
            body: { deleted: true },
        })
        return result
    },
})

const DashboardDeleteTileSchema = DashboardsDeleteTileParams.omit({ project_id: true })
    .extend(DashboardsDeleteTileBody.shape)
    .extend({ id: z.preprocess(castStringToInt, DashboardsDeleteTileParams.shape['id']) })

const dashboardDeleteTile = (): ToolBase<typeof DashboardDeleteTileSchema, unknown> => ({
    name: 'dashboard-delete-tile',
    schema: DashboardDeleteTileSchema,
    handler: async (context: Context, params: z.infer<typeof DashboardDeleteTileSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.tile_id !== undefined) {
            body['tile_id'] = params.tile_id
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/dashboards/${encodeURIComponent(String(params.id))}/delete_tile/`,
            body,
        })
        return await withPostHogUrl(context, result, `/dashboard/${params.id}`)
    },
})

const DashboardGetSchema = DashboardsRetrieveParams.omit({ project_id: true })
    .extend(DashboardsRetrieveQueryParams.omit({ format: true }).shape)
    .extend({ id: z.preprocess(castStringToInt, DashboardsRetrieveParams.shape['id']) })
    .extend({
        filters_override: z
            .union([z.string(), z.record(z.string(), z.unknown())])
            .optional()
            .describe(
                'Object (or pre-encoded JSON string) to override dashboard filters for this request only (not persisted). Top-level keys replace; nested values are not deep-merged — pass the complete value for any key you override. Accepts the same keys as the dashboard filters schema (e.g., `date_from`, `date_to`, `properties`). Ignored when accessed via a sharing token.'
            ),
        variables_override: z
            .union([z.string(), z.record(z.string(), z.unknown())])
            .optional()
            .describe(
                'Object (or pre-encoded JSON string) to override dashboard variables for this request only (not persisted). Format: {"<variable_id>": {"code_name": "<code_name>", "variableId": "<variable_id>", "value": <new_value>}}. Each entry must include `code_name` — partial entries are silently dropped. The simplest workflow is to call `dashboard-get` first, copy the matching entry from the response, and mutate `value`. Top-level keys replace; nested values are not deep-merged. Ignored when accessed via a sharing token.'
            ),
    })

const dashboardGet = (): ToolBase<typeof DashboardGetSchema, WithPostHogUrl<Schemas.Dashboard>> => ({
    name: 'dashboard-get',
    schema: DashboardGetSchema,
    handler: async (context: Context, params: z.infer<typeof DashboardGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Dashboard>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/dashboards/${encodeURIComponent(String(params.id))}/`,
            query: {
                filters_override: params.filters_override,
                variables_override: params.variables_override,
            },
        })
        const filtered = omitResponseFields(result, [
            'effective_restriction_level',
            'effective_privilege_level',
            'user_access_level',
            'access_control_version',
            'restriction_level',
            'creation_mode',
            'deleted',
            'breakdown_colors',
            'data_color_theme_id',
            'quick_filter_ids',
            'tiles.*.color',
            'tiles.*.transparent_background',
            'tiles.*.show_description',
            'tiles.*.button_tile',
            'tiles.*.insight.result',
            'tiles.*.insight.hasMore',
            'tiles.*.insight.columns',
            'tiles.*.insight.hogql',
            'tiles.*.insight.types',
            'tiles.*.insight.query_status',
            'tiles.*.insight.cache_target_age',
            'tiles.*.insight.next_allowed_client_refresh',
            'tiles.*.insight.filters_hash',
            'tiles.*.insight.dashboards',
            'tiles.*.insight.dashboard_tiles',
            'tiles.*.insight.effective_restriction_level',
            'tiles.*.insight.effective_privilege_level',
            'tiles.*.insight.user_access_level',
            'tiles.*.insight.filters',
            'tiles.*.insight.is_sample',
            'tiles.*.insight.order',
            'tiles.*.insight.deleted',
            'tiles.*.insight.alerts',
            'tiles.*.insight.timezone',
            'tiles.*.insight.resolved_date_range',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/dashboard/${filtered.id}`)
    },
})

const DashboardInsightsRunSchema = DashboardsRunInsightsRetrieveParams.omit({ project_id: true })
    .extend(DashboardsRunInsightsRetrieveQueryParams.omit({ format: true }).shape)
    .extend({ id: z.preprocess(castStringToInt, DashboardsRunInsightsRetrieveParams.shape['id']) })
    .extend({
        filters_override: z
            .union([z.string(), z.record(z.string(), z.unknown())])
            .optional()
            .describe(
                'Object (or pre-encoded JSON string) to override dashboard filters for this request only (not persisted). Top-level keys replace; nested values are not deep-merged — pass the complete value for any key you override. Accepts the same keys as the dashboard filters schema (e.g., `date_from`, `date_to`, `properties`). Ignored when accessed via a sharing token.'
            ),
        variables_override: z
            .union([z.string(), z.record(z.string(), z.unknown())])
            .optional()
            .describe(
                'Object (or pre-encoded JSON string) to override dashboard variables for this request only (not persisted). Format: {"<variable_id>": {"code_name": "<code_name>", "variableId": "<variable_id>", "value": <new_value>}}. Each entry must include `code_name` — partial entries are silently dropped. The simplest workflow is to call `dashboard-get` first, copy the matching entry from the response, and mutate `value`. Top-level keys replace; nested values are not deep-merged. Ignored when accessed via a sharing token.'
            ),
    })

const dashboardInsightsRun = (): ToolBase<
    typeof DashboardInsightsRunSchema,
    WithPostHogUrl<Schemas.RunInsightsResponse>
> => ({
    name: 'dashboard-insights-run',
    schema: DashboardInsightsRunSchema,
    handler: async (context: Context, params: z.infer<typeof DashboardInsightsRunSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.RunInsightsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/dashboards/${encodeURIComponent(String(params.id))}/run_insights/`,
            query: {
                filters_override: params.filters_override,
                output_format: params.output_format,
                refresh: params.refresh,
                variables_override: params.variables_override,
            },
        })
        return await withPostHogUrl(context, result, `/dashboard/${params.id}`)
    },
})

const DashboardReorderTilesSchema = DashboardsReorderTilesCreateParams.omit({ project_id: true }).extend(
    DashboardsReorderTilesCreateBody.shape
)

const dashboardReorderTiles = (): ToolBase<typeof DashboardReorderTilesSchema, WithPostHogUrl<Schemas.Dashboard>> => ({
    name: 'dashboard-reorder-tiles',
    schema: DashboardReorderTilesSchema,
    handler: async (context: Context, params: z.infer<typeof DashboardReorderTilesSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.tile_order !== undefined) {
            body['tile_order'] = params.tile_order
        }
        if (params.layout !== undefined) {
            body['layout'] = params.layout
        }
        const result = await context.api.request<Schemas.Dashboard>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/dashboards/${encodeURIComponent(String(params.id))}/reorder_tiles/`,
            body,
        })
        return await withPostHogUrl(context, result, `/dashboard/${result.id}`)
    },
})

const DashboardTileCopySchema = DashboardsCopyTileCreateParams.omit({ project_id: true })
    .extend(DashboardsCopyTileCreateBody.shape)
    .extend({ id: z.preprocess(castStringToInt, DashboardsCopyTileCreateParams.shape['id']) })

const dashboardTileCopy = (): ToolBase<typeof DashboardTileCopySchema, WithPostHogUrl<Schemas.Dashboard>> => ({
    name: 'dashboard-tile-copy',
    schema: DashboardTileCopySchema,
    handler: async (context: Context, params: z.infer<typeof DashboardTileCopySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.fromDashboardId !== undefined) {
            body['fromDashboardId'] = params.fromDashboardId
        }
        if (params.tileId !== undefined) {
            body['tileId'] = params.tileId
        }
        const result = await context.api.request<Schemas.Dashboard>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/dashboards/${encodeURIComponent(String(params.id))}/copy_tile/`,
            body,
        })
        return await withPostHogUrl(context, result, `/dashboard/${result.id}`)
    },
})

const DashboardUpdateSchema = DashboardsPartialUpdateParams.omit({ project_id: true })
    .extend(DashboardsPartialUpdateBody.shape)
    .extend({ id: z.preprocess(castStringToInt, DashboardsPartialUpdateParams.shape['id']) })

const dashboardUpdate = (): ToolBase<typeof DashboardUpdateSchema, WithPostHogUrl<Schemas.Dashboard>> => ({
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
        if (params.filters !== undefined) {
            body['filters'] = params.filters
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
        if (params.tiles !== undefined) {
            body['tiles'] = params.tiles
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/dashboards/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        const filtered = omitResponseFields(result, [
            'effective_restriction_level',
            'effective_privilege_level',
            'user_access_level',
            'access_control_version',
            'restriction_level',
            'creation_mode',
            'deleted',
            'breakdown_colors',
            'data_color_theme_id',
            'quick_filter_ids',
            'tiles.*.color',
            'tiles.*.transparent_background',
            'tiles.*.show_description',
            'tiles.*.button_tile',
            'tiles.*.insight.result',
            'tiles.*.insight.hasMore',
            'tiles.*.insight.columns',
            'tiles.*.insight.hogql',
            'tiles.*.insight.types',
            'tiles.*.insight.query_status',
            'tiles.*.insight.cache_target_age',
            'tiles.*.insight.next_allowed_client_refresh',
            'tiles.*.insight.filters_hash',
            'tiles.*.insight.dashboards',
            'tiles.*.insight.dashboard_tiles',
            'tiles.*.insight.effective_restriction_level',
            'tiles.*.insight.effective_privilege_level',
            'tiles.*.insight.user_access_level',
            'tiles.*.insight.filters',
            'tiles.*.insight.is_sample',
            'tiles.*.insight.order',
            'tiles.*.insight.deleted',
            'tiles.*.insight.alerts',
            'tiles.*.insight.timezone',
            'tiles.*.insight.resolved_date_range',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/dashboard/${filtered.id}`)
    },
})

const DashboardUpdateTextTileSchema = DashboardsUpdateTextTileCreateParams.omit({ project_id: true })
    .extend(DashboardsUpdateTextTileCreateBody.shape)
    .extend({ id: z.preprocess(castStringToInt, DashboardsUpdateTextTileCreateParams.shape['id']) })

const dashboardUpdateTextTile = (): ToolBase<
    typeof DashboardUpdateTextTileSchema,
    WithPostHogUrl<Schemas.DashboardTile>
> => ({
    name: 'dashboard-update-text-tile',
    schema: DashboardUpdateTextTileSchema,
    handler: async (context: Context, params: z.infer<typeof DashboardUpdateTextTileSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.tile_id !== undefined) {
            body['tile_id'] = params.tile_id
        }
        if (params.body !== undefined) {
            body['body'] = params.body
        }
        if (params.layouts !== undefined) {
            body['layouts'] = params.layouts
        }
        if (params.color !== undefined) {
            body['color'] = params.color
        }
        const result = await context.api.request<Schemas.DashboardTile>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/dashboards/${encodeURIComponent(String(params.id))}/update_text_tile/`,
            body,
        })
        return await withPostHogUrl(context, result, `/dashboard/${params.id}`)
    },
})

const DashboardWidgetCatalogListSchema = z.object({})

const dashboardWidgetCatalogList = (): ToolBase<
    typeof DashboardWidgetCatalogListSchema,
    Schemas.WidgetCatalogResponse
> => ({
    name: 'dashboard-widget-catalog-list',
    schema: DashboardWidgetCatalogListSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof DashboardWidgetCatalogListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.WidgetCatalogResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/dashboards/widget_catalog/`,
        })
        return result
    },
})

const DashboardWidgetsBatchAddSchema = DashboardsWidgetsBatchCreateParams.omit({ project_id: true })
    .extend(DashboardsWidgetsBatchCreateBody.shape)
    .extend({ id: z.preprocess(castStringToInt, DashboardsWidgetsBatchCreateParams.shape['id']) })

const dashboardWidgetsBatchAdd = (): ToolBase<
    typeof DashboardWidgetsBatchAddSchema,
    WithPostHogUrl<Schemas.AddDashboardWidgetsBatchResponse>
> => ({
    name: 'dashboard-widgets-batch-add',
    schema: DashboardWidgetsBatchAddSchema,
    handler: async (context: Context, params: z.infer<typeof DashboardWidgetsBatchAddSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.widgets !== undefined) {
            body['widgets'] = params.widgets
        }
        const result = await context.api.request<Schemas.AddDashboardWidgetsBatchResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/dashboards/${encodeURIComponent(String(params.id))}/widgets/batch/`,
            body,
        })
        return await withPostHogUrl(context, result, `/dashboard/${params.id}`)
    },
})

const DashboardWidgetsBatchUpdateSchema = DashboardsUpdateWidgetsBatchParams.omit({ project_id: true })
    .extend(DashboardsUpdateWidgetsBatchBody.shape)
    .extend({ id: z.preprocess(castStringToInt, DashboardsUpdateWidgetsBatchParams.shape['id']) })

const dashboardWidgetsBatchUpdate = (): ToolBase<
    typeof DashboardWidgetsBatchUpdateSchema,
    WithPostHogUrl<Schemas.UpdateDashboardWidgetsBatchResponse>
> => ({
    name: 'dashboard-widgets-batch-update',
    schema: DashboardWidgetsBatchUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof DashboardWidgetsBatchUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.widgets !== undefined) {
            body['widgets'] = params.widgets
        }
        const result = await context.api.request<Schemas.UpdateDashboardWidgetsBatchResponse>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/dashboards/${encodeURIComponent(String(params.id))}/widgets/batch_update/`,
            body,
        })
        return await withPostHogUrl(context, result, `/dashboard/${params.id}`)
    },
})

const DashboardWidgetsRunSchema = DashboardsRunWidgetsRetrieveParams.omit({ project_id: true })
    .extend(DashboardsRunWidgetsRetrieveQueryParams.omit({ format: true }).shape)
    .extend({ id: z.preprocess(castStringToInt, DashboardsRunWidgetsRetrieveParams.shape['id']) })

const dashboardWidgetsRun = (): ToolBase<
    typeof DashboardWidgetsRunSchema,
    WithPostHogUrl<Schemas.RunWidgetsResponse>
> => ({
    name: 'dashboard-widgets-run',
    schema: DashboardWidgetsRunSchema,
    handler: async (context: Context, params: z.infer<typeof DashboardWidgetsRunSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.RunWidgetsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/dashboards/${encodeURIComponent(String(params.id))}/run_widgets/`,
            query: {
                tile_ids: params.tile_ids,
            },
        })
        return await withPostHogUrl(context, result, `/dashboard/${params.id}`)
    },
})

const DashboardsGetAllSchema = DashboardsListQueryParams.omit({ format: true }).extend({
    limit: z.preprocess(castStringToInt, DashboardsListQueryParams.shape['limit']).optional(),
    offset: z.preprocess(castStringToInt, DashboardsListQueryParams.shape['offset']).optional(),
})

const dashboardsGetAll = (): ToolBase<
    typeof DashboardsGetAllSchema,
    WithPostHogUrl<Schemas.PaginatedDashboardBasicList>
> => ({
    name: 'dashboards-get-all',
    schema: DashboardsGetAllSchema,
    handler: async (context: Context, params: z.infer<typeof DashboardsGetAllSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedDashboardBasicList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/dashboards/`,
            query: {
                folder: params.folder,
                limit: params.limit,
                offset: params.offset,
                search: params.search,
            },
        })
        return await withPostHogUrl(
            context,
            {
                ...result,
                results: await Promise.all(
                    (result.results ?? []).map((item) => withPostHogUrl(context, item, `/dashboard/${item.id}`))
                ),
            },
            '/dashboard'
        )
    },
})

const DashboardsMoveTilePartialUpdateSchema = DashboardsMoveTilePartialUpdateParams.omit({ project_id: true })
    .extend(DashboardsMoveTilePartialUpdateBody.shape)
    .extend({ id: z.preprocess(castStringToInt, DashboardsMoveTilePartialUpdateParams.shape['id']) })

const dashboardsMoveTilePartialUpdate = (): ToolBase<
    typeof DashboardsMoveTilePartialUpdateSchema,
    WithPostHogUrl<Schemas.Dashboard>
> => ({
    name: 'dashboards-move-tile-partial-update',
    schema: DashboardsMoveTilePartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof DashboardsMoveTilePartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.to_dashboard !== undefined) {
            body['to_dashboard'] = params.to_dashboard
        }
        if (params.tile !== undefined) {
            body['tile'] = params.tile
        }
        const result = await context.api.request<Schemas.Dashboard>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/dashboards/${encodeURIComponent(String(params.id))}/move_tile/`,
            body,
        })
        return await withPostHogUrl(context, result, `/dashboard/${result.id}`)
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'dashboard-create': dashboardCreate,
    'dashboard-create-text-tile': dashboardCreateTextTile,
    'dashboard-delete': dashboardDelete,
    'dashboard-delete-tile': dashboardDeleteTile,
    'dashboard-get': dashboardGet,
    'dashboard-insights-run': dashboardInsightsRun,
    'dashboard-reorder-tiles': dashboardReorderTiles,
    'dashboard-tile-copy': dashboardTileCopy,
    'dashboard-update': dashboardUpdate,
    'dashboard-update-text-tile': dashboardUpdateTextTile,
    'dashboard-widget-catalog-list': dashboardWidgetCatalogList,
    'dashboard-widgets-batch-add': dashboardWidgetsBatchAdd,
    'dashboard-widgets-batch-update': dashboardWidgetsBatchUpdate,
    'dashboard-widgets-run': dashboardWidgetsRun,
    'dashboards-get-all': dashboardsGetAll,
    'dashboards-move-tile-partial-update': dashboardsMoveTilePartialUpdate,
}
