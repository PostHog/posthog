/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 15 enabled ops
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

/**
 * Add a markdown text tile to a dashboard.

Text tiles render as markdown blocks on the dashboard — useful as section headings, dividers,
or annotations between insight tiles to give the dashboard structure.
 */
export const DashboardsCreateTextTileCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsCreateTextTileCreateQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const dashboardsCreateTextTileCreateBodyBodyMax = 4000

export const dashboardsCreateTextTileCreateBodyColorMax = 400

export const DashboardsCreateTextTileCreateBody = /* @__PURE__ */ zod.object({
    body: zod
        .string()
        .min(1)
        .max(dashboardsCreateTextTileCreateBodyBodyMax)
        .describe(
            'Markdown body for the text tile. Supports headings, lists, and inline formatting. Useful as a dashboard section heading, divider, or annotation between insights. Max 4000 characters.'
        ),
    layouts: zod
        .object({
            sm: zod
                .object({
                    x: zod.number().optional().describe('Column position in the dashboard grid (0-indexed).'),
                    y: zod.number().optional().describe('Row position in the dashboard grid (0-indexed).'),
                    w: zod.number().optional().describe('Width in grid columns. The desktop grid is 12 columns wide.'),
                    h: zod.number().optional().describe('Height in grid rows.'),
                })
                .optional()
                .describe('Layout for the standard (desktop) breakpoint. The grid is 12 columns wide.'),
            xs: zod
                .object({
                    x: zod.number().optional().describe('Column position in the dashboard grid (0-indexed).'),
                    y: zod.number().optional().describe('Row position in the dashboard grid (0-indexed).'),
                    w: zod.number().optional().describe('Width in grid columns. The desktop grid is 12 columns wide.'),
                    h: zod.number().optional().describe('Height in grid rows.'),
                })
                .optional()
                .describe('Layout for the small (mobile) breakpoint. The grid is 1 column wide.'),
        })
        .optional()
        .describe(
            'Optional grid layout per breakpoint. If omitted, the tile is placed at the bottom of the dashboard using the default size. Text tiles typically use a thin full-width banner (e.g. w=12, h=1).'
        ),
    color: zod
        .string()
        .max(dashboardsCreateTextTileCreateBodyColorMax)
        .nullish()
        .describe("Optional accent color name (e.g. 'blue', 'green', 'purple', 'black')."),
})

/**
 * Soft-delete a single tile from a dashboard.

Works for text, insight, and button tiles. The underlying Insight, Text, or ButtonTile
object is preserved — only the dashboard tile is hidden. To delete the entire dashboard,
use the dashboard delete endpoint instead.
 */
export const DashboardsDeleteTileParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsDeleteTileQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const DashboardsDeleteTileBody = /* @__PURE__ */ zod.object({
    tile_id: zod.number().describe('ID of the dashboard tile to delete. Use dashboard-get to look up tile IDs.'),
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
    to_dashboard: zod.number().optional().describe('Destination dashboard ID.'),
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

export const dashboardsReorderTilesCreateBodyLayoutDefault = `preserve`

export const DashboardsReorderTilesCreateBody = /* @__PURE__ */ zod.object({
    tile_order: zod
        .array(zod.number())
        .min(1)
        .describe('Array of tile IDs in the desired display order (top to bottom, left to right).'),
    layout: zod
        .enum(['preserve', 'two_column', 'full_width'])
        .describe('* `preserve` - preserve\n* `two_column` - two_column\n* `full_width` - full_width')
        .default(dashboardsReorderTilesCreateBodyLayoutDefault)
        .describe(
            "How to size tiles when reordering. 'preserve' (default) keeps each tile's existing width and height and only repacks positions in the new order. 'two_column' forces a 6-wide × 5-tall grid (two tiles per row). 'full_width' forces each tile to span the full 12-column row at height 5.\n\n* `preserve` - preserve\n* `two_column` - two_column\n* `full_width` - full_width"
        ),
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
 * Update the markdown body, layout, or color of an existing text tile on a dashboard.
 */
export const DashboardsUpdateTextTileCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsUpdateTextTileCreateQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const dashboardsUpdateTextTileCreateBodyBodyMax = 4000

export const dashboardsUpdateTextTileCreateBodyColorMax = 400

export const DashboardsUpdateTextTileCreateBody = /* @__PURE__ */ zod.object({
    tile_id: zod.number().describe('ID of the dashboard tile to update. Use dashboard-get to look up tile IDs.'),
    body: zod
        .string()
        .min(1)
        .max(dashboardsUpdateTextTileCreateBodyBodyMax)
        .optional()
        .describe('New markdown body for the text tile. Omit to leave the body unchanged. Max 4000 characters.'),
    layouts: zod
        .object({
            sm: zod
                .object({
                    x: zod.number().optional().describe('Column position in the dashboard grid (0-indexed).'),
                    y: zod.number().optional().describe('Row position in the dashboard grid (0-indexed).'),
                    w: zod.number().optional().describe('Width in grid columns. The desktop grid is 12 columns wide.'),
                    h: zod.number().optional().describe('Height in grid rows.'),
                })
                .optional()
                .describe('Layout for the standard (desktop) breakpoint. The grid is 12 columns wide.'),
            xs: zod
                .object({
                    x: zod.number().optional().describe('Column position in the dashboard grid (0-indexed).'),
                    y: zod.number().optional().describe('Row position in the dashboard grid (0-indexed).'),
                    w: zod.number().optional().describe('Width in grid columns. The desktop grid is 12 columns wide.'),
                    h: zod.number().optional().describe('Height in grid rows.'),
                })
                .optional()
                .describe('Layout for the small (mobile) breakpoint. The grid is 1 column wide.'),
        })
        .optional()
        .describe('New grid layout per breakpoint. Omit to leave the layout unchanged.'),
    color: zod
        .string()
        .max(dashboardsUpdateTextTileCreateBodyColorMax)
        .nullish()
        .describe('New accent color name, empty string or null to clear. Omit to leave unchanged.'),
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

export const dashboardsWidgetsBatchCreateBodyWidgetsItemOneNameMax = 400

export const dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneLimitDefault = 10
export const dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneLimitMax = 25

export const dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneOrderByDefault = `occurrences`
export const dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneOrderDirectionDefault = `DESC`
export const dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneStatusDefault = `active`
export const dashboardsWidgetsBatchCreateBodyWidgetsItemTwoNameMax = 400

export const dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneLimitDefault = 10
export const dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneLimitMax = 25

export const dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneOrderByDefault = `start_time`
export const dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneOrderDirectionDefault = `DESC`
export const dashboardsWidgetsBatchCreateBodyWidgetsMax = 10

export const DashboardsWidgetsBatchCreateBody = /* @__PURE__ */ zod
    .object({
        widgets: zod
            .array(
                zod.union([
                    zod.object({
                        name: zod
                            .string()
                            .max(dashboardsWidgetsBatchCreateBodyWidgetsItemOneNameMax)
                            .nullish()
                            .describe('Optional custom display name for the widget tile.'),
                        description: zod
                            .string()
                            .optional()
                            .describe('Optional markdown description shown when show_description is enabled.'),
                        layouts: zod
                            .object({
                                sm: zod
                                    .object({
                                        x: zod
                                            .number()
                                            .optional()
                                            .describe('Column position in the dashboard grid (0-indexed).'),
                                        y: zod
                                            .number()
                                            .optional()
                                            .describe('Row position in the dashboard grid (0-indexed).'),
                                        w: zod
                                            .number()
                                            .optional()
                                            .describe('Width in grid columns. The desktop grid is 12 columns wide.'),
                                        h: zod.number().optional().describe('Height in grid rows.'),
                                    })
                                    .optional()
                                    .describe(
                                        'Layout for the standard (desktop) breakpoint. The grid is 12 columns wide.'
                                    ),
                                xs: zod
                                    .object({
                                        x: zod
                                            .number()
                                            .optional()
                                            .describe('Column position in the dashboard grid (0-indexed).'),
                                        y: zod
                                            .number()
                                            .optional()
                                            .describe('Row position in the dashboard grid (0-indexed).'),
                                        w: zod
                                            .number()
                                            .optional()
                                            .describe('Width in grid columns. The desktop grid is 12 columns wide.'),
                                        h: zod.number().optional().describe('Height in grid rows.'),
                                    })
                                    .optional()
                                    .describe('Layout for the small (mobile) breakpoint. The grid is 1 column wide.'),
                            })
                            .optional()
                            .describe('Optional react-grid-layout positions keyed by breakpoint (sm, xs).'),
                        show_description: zod
                            .boolean()
                            .optional()
                            .describe('Whether to show the description on the dashboard tile.'),
                        widget_type: zod.enum(['error_tracking_list']),
                        config: zod
                            .object({
                                limit: zod
                                    .number()
                                    .min(1)
                                    .max(dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneLimitMax)
                                    .default(dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneLimitDefault)
                                    .describe('Maximum number of issues to return (page size).'),
                                orderBy: zod
                                    .enum(['last_seen', 'first_seen', 'occurrences', 'users', 'sessions'])
                                    .describe(
                                        '* `last_seen` - last_seen\n* `first_seen` - first_seen\n* `occurrences` - occurrences\n* `users` - users\n* `sessions` - sessions'
                                    )
                                    .default(dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneOrderByDefault)
                                    .describe(
                                        'Issue ranking column.\n\n* `first_seen` - first_seen\n* `last_seen` - last_seen\n* `occurrences` - occurrences\n* `sessions` - sessions\n* `users` - users'
                                    ),
                                orderDirection: zod
                                    .enum(['ASC', 'DESC'])
                                    .describe('* `ASC` - ASC\n* `DESC` - DESC')
                                    .default(
                                        dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneOrderDirectionDefault
                                    )
                                    .describe('Sort direction for orderBy.\n\n* `ASC` - ASC\n* `DESC` - DESC'),
                                status: zod
                                    .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed', 'all'])
                                    .describe(
                                        '* `archived` - archived\n* `active` - active\n* `resolved` - resolved\n* `pending_release` - pending_release\n* `suppressed` - suppressed\n* `all` - all'
                                    )
                                    .default(dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneStatusDefault)
                                    .describe(
                                        'Issue status filter.\n\n* `archived` - archived\n* `active` - active\n* `resolved` - resolved\n* `pending_release` - pending_release\n* `suppressed` - suppressed\n* `all` - all'
                                    ),
                                assignee: zod
                                    .union([
                                        zod.object({
                                            id: zod
                                                .union([zod.string(), zod.number(), zod.null()])
                                                .describe('User ID or role UUID to filter by.'),
                                            type: zod
                                                .enum(['user', 'role'])
                                                .describe('* `user` - user\n* `role` - role')
                                                .describe(
                                                    'Assignee target type: user or role.\n\n* `user` - user\n* `role` - role'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Filter by assignee ({type: user|role, id}). Omit for any assignee.'),
                                widgetFilters: zod
                                    .record(
                                        zod.string(),
                                        zod.object({
                                            filterId: zod
                                                .string()
                                                .describe('Filter UUID; must match the widgetFilters map key.'),
                                            propertyName: zod
                                                .string()
                                                .describe('Event property key (for example $environment).'),
                                            optionId: zod
                                                .string()
                                                .describe('Selected option id from the filter definition.'),
                                            operator: zod
                                                .string()
                                                .describe(
                                                    'Property filter operator (for example exact, is_not, icontains).'
                                                ),
                                            value: zod
                                                .unknown()
                                                .optional()
                                                .describe('Filter value as a string, list of strings, or null.'),
                                        })
                                    )
                                    .optional()
                                    .describe(
                                        "Widget filter selections keyed by filter id. Each key must match the entry's filterId. Configure filters in the product UI first, then copy filter id, option id, and property name here."
                                    ),
                                dateRange: zod
                                    .union([
                                        zod.object({
                                            date_from: zod
                                                .union([
                                                    zod
                                                        .enum(['-14d', '-1h', '-24h', '-30d', '-3h', '-7d', '-90d'])
                                                        .describe(
                                                            '* `-14d` - -14d\n* `-1h` - -1h\n* `-24h` - -24h\n* `-30d` - -30d\n* `-3h` - -3h\n* `-7d` - -7d\n* `-90d` - -90d'
                                                        ),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe(
                                                    "Relative lookback window (for example '-7d'). Omit to use the project default range.\n\n* `-14d` - -14d\n* `-1h` - -1h\n* `-24h` - -24h\n* `-30d` - -30d\n* `-3h` - -3h\n* `-7d` - -7d\n* `-90d` - -90d"
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Relative date range for issues (date_from only on widgets).'),
                                filterTestAccounts: zod
                                    .boolean()
                                    .optional()
                                    .describe('When omitted, follows the project default for filtering test accounts.'),
                            })
                            .describe('Configuration for the error tracking list widget.'),
                    }),
                    zod.object({
                        name: zod
                            .string()
                            .max(dashboardsWidgetsBatchCreateBodyWidgetsItemTwoNameMax)
                            .nullish()
                            .describe('Optional custom display name for the widget tile.'),
                        description: zod
                            .string()
                            .optional()
                            .describe('Optional markdown description shown when show_description is enabled.'),
                        layouts: zod
                            .object({
                                sm: zod
                                    .object({
                                        x: zod
                                            .number()
                                            .optional()
                                            .describe('Column position in the dashboard grid (0-indexed).'),
                                        y: zod
                                            .number()
                                            .optional()
                                            .describe('Row position in the dashboard grid (0-indexed).'),
                                        w: zod
                                            .number()
                                            .optional()
                                            .describe('Width in grid columns. The desktop grid is 12 columns wide.'),
                                        h: zod.number().optional().describe('Height in grid rows.'),
                                    })
                                    .optional()
                                    .describe(
                                        'Layout for the standard (desktop) breakpoint. The grid is 12 columns wide.'
                                    ),
                                xs: zod
                                    .object({
                                        x: zod
                                            .number()
                                            .optional()
                                            .describe('Column position in the dashboard grid (0-indexed).'),
                                        y: zod
                                            .number()
                                            .optional()
                                            .describe('Row position in the dashboard grid (0-indexed).'),
                                        w: zod
                                            .number()
                                            .optional()
                                            .describe('Width in grid columns. The desktop grid is 12 columns wide.'),
                                        h: zod.number().optional().describe('Height in grid rows.'),
                                    })
                                    .optional()
                                    .describe('Layout for the small (mobile) breakpoint. The grid is 1 column wide.'),
                            })
                            .optional()
                            .describe('Optional react-grid-layout positions keyed by breakpoint (sm, xs).'),
                        show_description: zod
                            .boolean()
                            .optional()
                            .describe('Whether to show the description on the dashboard tile.'),
                        widget_type: zod.enum(['session_replay_list']),
                        config: zod
                            .object({
                                limit: zod
                                    .number()
                                    .min(1)
                                    .max(dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneLimitMax)
                                    .default(dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneLimitDefault)
                                    .describe('Maximum number of recordings to return.'),
                                orderBy: zod
                                    .enum([
                                        'activity_score',
                                        'click_count',
                                        'console_error_count',
                                        'duration',
                                        'recording_duration',
                                        'start_time',
                                    ])
                                    .describe(
                                        '* `activity_score` - activity_score\n* `click_count` - click_count\n* `console_error_count` - console_error_count\n* `duration` - duration\n* `recording_duration` - recording_duration\n* `start_time` - start_time'
                                    )
                                    .default(dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneOrderByDefault)
                                    .describe(
                                        'Recording ranking column.\n\n* `activity_score` - activity_score\n* `click_count` - click_count\n* `console_error_count` - console_error_count\n* `duration` - duration\n* `recording_duration` - recording_duration\n* `start_time` - start_time'
                                    ),
                                orderDirection: zod
                                    .enum(['ASC', 'DESC'])
                                    .describe('* `ASC` - ASC\n* `DESC` - DESC')
                                    .default(
                                        dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneOrderDirectionDefault
                                    )
                                    .describe('Sort direction for orderBy.\n\n* `ASC` - ASC\n* `DESC` - DESC'),
                                dateRange: zod
                                    .union([
                                        zod.object({
                                            date_from: zod
                                                .union([
                                                    zod
                                                        .enum(['-14d', '-1h', '-24h', '-30d', '-3h', '-7d', '-90d'])
                                                        .describe(
                                                            '* `-14d` - -14d\n* `-1h` - -1h\n* `-24h` - -24h\n* `-30d` - -30d\n* `-3h` - -3h\n* `-7d` - -7d\n* `-90d` - -90d'
                                                        ),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe(
                                                    "Relative lookback window (for example '-7d'). Omit to use the project default range.\n\n* `-14d` - -14d\n* `-1h` - -1h\n* `-24h` - -24h\n* `-30d` - -30d\n* `-3h` - -3h\n* `-7d` - -7d\n* `-90d` - -90d"
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Optional relative date range override.'),
                                widgetFilters: zod
                                    .record(
                                        zod.string(),
                                        zod.object({
                                            filterId: zod
                                                .string()
                                                .describe('Filter UUID; must match the widgetFilters map key.'),
                                            propertyName: zod
                                                .string()
                                                .describe('Event property key (for example $environment).'),
                                            optionId: zod
                                                .string()
                                                .describe('Selected option id from the filter definition.'),
                                            operator: zod
                                                .string()
                                                .describe(
                                                    'Property filter operator (for example exact, is_not, icontains).'
                                                ),
                                            value: zod
                                                .unknown()
                                                .optional()
                                                .describe('Filter value as a string, list of strings, or null.'),
                                        })
                                    )
                                    .optional()
                                    .describe(
                                        "Widget filter selections keyed by filter id. Each key must match the entry's filterId. Configure filters in the product UI first, then copy filter id, option id, and property name here."
                                    ),
                                filterTestAccounts: zod
                                    .boolean()
                                    .optional()
                                    .describe('When omitted, follows the project default for filtering test accounts.'),
                            })
                            .describe('Configuration for the session replay list widget.'),
                    }),
                ])
            )
            .min(1)
            .max(dashboardsWidgetsBatchCreateBodyWidgetsMax)
            .describe(
                'Widget tiles to add atomically. Supported widget_type values: error_tracking_list, session_replay_list. Use dashboard-widget-catalog-list for config_schema_hints per type. (1–10 per request).'
            ),
    })
    .describe('OpenAPI-only batch-add schema with widget_type-discriminated config shapes for agents.')

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
