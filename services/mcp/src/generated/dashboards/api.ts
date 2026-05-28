/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 14 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const DashboardsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsListQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['json', 'txt']).optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod
        .string()
        .optional()
        .describe(
            'Optional. Fuzzy match against dashboard `name` and `description` using Postgres trigram word similarity (handles typos, transpositions, and prefix-as-you-type). `name` matches rank above `description` matches. Results are ordered by relevance, then pinned status, then name. When omitted, dashboards are ordered by pinned status then alphabetical name. Capped at 200 characters; longer queries return a 400 error.'
        ),
})

export const DashboardsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsCreateQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const dashboardsCreateBodyNameMax = 400

export const dashboardsCreateBodyDeleteInsightsDefault = false

export const DashboardsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsCreateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .optional()
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            ),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsCreateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const DashboardsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    filters_override: zod
        .string()
        .optional()
        .describe(
            'Object (or pre-encoded JSON string) to override dashboard filters for this request only (not persisted). Top-level keys replace; nested values are not deep-merged — pass the complete value for any key you override. Accepts the same keys as the dashboard filters schema (e.g., `date_from`, `date_to`, `properties`). Ignored when accessed via a sharing token.'
        ),
    format: zod.enum(['json', 'txt']).optional(),
    variables_override: zod
        .string()
        .optional()
        .describe(
            'Object (or pre-encoded JSON string) to override dashboard variables for this request only (not persisted). Format: {"<variable_id>": {"code_name": "<code_name>", "variableId": "<variable_id>", "value": <new_value>}}. Each entry must include `code_name` — partial entries are silently dropped. The simplest workflow is to call `dashboard-get` first, copy the matching entry from the response, and mutate `value`. Top-level keys replace; nested values are not deep-merged. Ignored when accessed via a sharing token.'
        ),
})

export const DashboardsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsPartialUpdateQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const dashboardsPartialUpdateBodyNameMax = 400

export const DashboardsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsPartialUpdateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .optional()
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            ),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .optional()
            .describe('When deleting, also delete insights that are only on this dashboard.'),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const DashboardsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsDestroyQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

/**
 * Copy an existing dashboard tile to another dashboard (insight, text card, or widget tile).
 */
export const DashboardsCopyTileCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsCopyTileCreateQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const DashboardsCopyTileCreateBody = /* @__PURE__ */ zod.object({
    fromDashboardId: zod.number().describe('Dashboard id the tile currently belongs to.'),
    tileId: zod.number().describe('Dashboard tile id to copy.'),
})

export const DashboardsMoveTilePartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsMoveTilePartialUpdateQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const DashboardsMoveTilePartialUpdateBody = /* @__PURE__ */ zod.object({
    toDashboard: zod.number().optional().describe('Destination dashboard ID.'),
    tile: zod
        .object({
            id: zod.number().describe('Dashboard tile ID to move.'),
        })
        .optional()
        .describe('Tile to move, identified by its dashboard tile ID.'),
})

export const DashboardsReorderTilesCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsReorderTilesCreateQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const DashboardsReorderTilesCreateBody = /* @__PURE__ */ zod.object({
    tile_order: zod
        .array(zod.number())
        .min(1)
        .describe('Array of tile IDs in the desired display order (top to bottom, left to right).'),
})

/**
 * Run all insights on a dashboard and return their results.
 */
export const DashboardsRunInsightsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsRunInsightsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    filters_override: zod
        .string()
        .optional()
        .describe(
            'Object (or pre-encoded JSON string) to override dashboard filters for this request only (not persisted). Top-level keys replace; nested values are not deep-merged — pass the complete value for any key you override. Accepts the same keys as the dashboard filters schema (e.g., `date_from`, `date_to`, `properties`). Ignored when accessed via a sharing token.'
        ),
    format: zod.enum(['json', 'txt']).optional(),
    output_format: zod
        .enum(['json', 'optimized'])
        .optional()
        .describe(
            "'optimized' (default) returns LLM-friendly formatted text per insight. 'json' returns the raw query result objects."
        ),
    refresh: zod
        .enum(['blocking', 'force_blocking', 'force_cache'])
        .optional()
        .describe(
            "Cache behavior. 'force_cache' (default) serves from cache even if stale. 'blocking' uses cache if fresh, otherwise recalculates. 'force_blocking' always recalculates."
        ),
    variables_override: zod
        .string()
        .optional()
        .describe(
            'Object (or pre-encoded JSON string) to override dashboard variables for this request only (not persisted). Format: {"<variable_id>": {"code_name": "<code_name>", "variableId": "<variable_id>", "value": <new_value>}}. Each entry must include `code_name` — partial entries are silently dropped. The simplest workflow is to call `dashboard-get` first, copy the matching entry from the response, and mutate `value`. Top-level keys replace; nested values are not deep-merged. Ignored when accessed via a sharing token.'
        ),
})

export const DashboardsRunWidgetsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsRunWidgetsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['json', 'txt']).optional(),
    tile_ids: zod.string().describe('Comma-separated dashboard tile IDs to run widgets for.'),
})

/**
 * Add a widget tile to a dashboard.
 */
export const DashboardsWidgetsCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsWidgetsCreateQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const dashboardsWidgetsCreateBodyWidgetTypeMax = 64

export const dashboardsWidgetsCreateBodyNameMax = 400

export const DashboardsWidgetsCreateBody = /* @__PURE__ */ zod.object({
    widget_type: zod
        .string()
        .max(dashboardsWidgetsCreateBodyWidgetTypeMax)
        .describe('Widget type identifier from dashboard-widget-catalog-list.'),
    config: zod
        .unknown()
        .describe(
            'Widget-specific configuration JSON. Shape depends on widget_type; see config_schema_hints in dashboard-widget-catalog-list.'
        ),
    name: zod
        .string()
        .max(dashboardsWidgetsCreateBodyNameMax)
        .nullish()
        .describe('Optional custom display name for the widget tile.'),
    description: zod
        .string()
        .optional()
        .describe('Optional markdown description shown when show_description is enabled.'),
    layouts: zod.unknown().optional().describe('Optional react-grid-layout positions keyed by breakpoint (sm, xs).'),
    show_description: zod.boolean().optional().describe('Whether to show the description on the dashboard tile.'),
})

/**
 * Update an existing widget tile on a dashboard.
 */
export const DashboardsWidgetsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    tile_id: zod.number().describe('Dashboard tile ID from dashboard-get (must be a widget tile).'),
})

export const DashboardsWidgetsPartialUpdateQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const dashboardsWidgetsPartialUpdateBodyNameMax = 400

export const DashboardsWidgetsPartialUpdateBody = /* @__PURE__ */ zod.object({
    config: zod
        .unknown()
        .optional()
        .describe("Updated widget configuration JSON. Validated for the tile's widget_type."),
    name: zod
        .string()
        .max(dashboardsWidgetsPartialUpdateBodyNameMax)
        .nullish()
        .describe('Optional custom display name for the widget tile.'),
    description: zod
        .string()
        .optional()
        .describe('Optional markdown description shown when show_description is enabled.'),
    show_description: zod.boolean().optional().describe('Whether to show the description on the dashboard tile.'),
    layouts: zod.unknown().optional().describe('Optional react-grid-layout positions keyed by breakpoint (sm, xs).'),
})

/**
 * Add multiple widget tiles to a dashboard in one atomic request.
 */
export const DashboardsWidgetsBatchCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsWidgetsBatchCreateQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const dashboardsWidgetsBatchCreateBodyWidgetsItemWidgetTypeMax = 64

export const dashboardsWidgetsBatchCreateBodyWidgetsItemNameMax = 400

export const dashboardsWidgetsBatchCreateBodyWidgetsMax = 10

export const DashboardsWidgetsBatchCreateBody = /* @__PURE__ */ zod.object({
    widgets: zod
        .array(
            zod.object({
                widget_type: zod
                    .string()
                    .max(dashboardsWidgetsBatchCreateBodyWidgetsItemWidgetTypeMax)
                    .describe('Widget type identifier from dashboard-widget-catalog-list.'),
                config: zod
                    .unknown()
                    .describe(
                        'Widget-specific configuration JSON. Shape depends on widget_type; see config_schema_hints in dashboard-widget-catalog-list.'
                    ),
                name: zod
                    .string()
                    .max(dashboardsWidgetsBatchCreateBodyWidgetsItemNameMax)
                    .nullish()
                    .describe('Optional custom display name for the widget tile.'),
                description: zod
                    .string()
                    .optional()
                    .describe('Optional markdown description shown when show_description is enabled.'),
                layouts: zod
                    .unknown()
                    .optional()
                    .describe('Optional react-grid-layout positions keyed by breakpoint (sm, xs).'),
                show_description: zod
                    .boolean()
                    .optional()
                    .describe('Whether to show the description on the dashboard tile.'),
            })
        )
        .min(1)
        .max(dashboardsWidgetsBatchCreateBodyWidgetsMax)
        .describe('Widget tiles to add atomically (1–10). Each entry uses the same fields as a single add request.'),
})

/**
 * List registered dashboard widget types and config hints for agents.
 */
export const DashboardsWidgetCatalogRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsWidgetCatalogRetrieveQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})
