/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 19 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const DashboardTemplatesListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DashboardTemplatesListQueryParams = () => zod.object({
    is_featured: zod
        .boolean()
        .optional()
        .describe(
            'Omit for all templates. When set, filter by featured flag; parsed with str_to_bool (same as other API query booleans).'
        ),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    ordering: zod
        .string()
        .optional()
        .describe(
            'Optional. When not using `search`, results are sorted with featured templates first (`is_featured=true`), then by `template_name` (case-insensitive A–Z; `-template_name` for Z–A) or by `created_at` (`-created_at` for newest first). When `search` is set, order is featured first, then relevance rank, then case-insensitive name for ties.'
        ),
    scope: zod
        .enum(['feature_flag', 'global', 'organization', 'team'])
        .optional()
        .describe(
            "Optional. `global`: official templates only. `team`: this project's saved templates only (`scope=team` rows for the current project). `organization`: templates shared across all projects in this organization. `feature_flag`: feature-flag dashboard templates only. Omit for official, organization, and this project's templates (default dashboard template picker behavior)."
        ),
    search: zod
        .string()
        .optional()
        .describe(
            'Optional. Full-text search across template name, tags, and description, ranked by relevance. Use it to find templates for a topic (e.g. `retention`, `revenue`, `product analytics`).'
        ),
})

export const DashboardTemplatesRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this dashboard template.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DashboardsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DashboardsListQueryParams = () => zod.object({
    created_by: zod
        .string()
        .optional()
        .describe('Optional. Return only dashboards created by the user with this UUID.'),
    exclude_generated: zod.boolean().optional().describe('Optional. Exclude dashboards that PostHog generated.'),
    folder: zod
        .string()
        .optional()
        .describe(
            "Optional. Return only dashboards filed directly in this project-tree folder, e.g. 'Unfiled\/Dashboards'. An empty string matches dashboards at the project root. Nested sub-folders are not included."
        ),
    format: zod.enum(['json', 'txt']).optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    ordering: zod
        .enum(['-last_viewed_at'])
        .optional()
        .describe(
            'Optional. `-last_viewed_at` puts the dashboards you viewed most recently first. A dashboard you never viewed sorts by its creation time. This order replaces the search relevance order.'
        ),
    pinned: zod.boolean().optional().describe('Optional. Return only pinned dashboards.'),
    search: zod
        .string()
        .optional()
        .describe(
            "Optional. Match against dashboard `name`, `description`, and tag names. Returns exact (case-insensitive substring) matches only; if no exact match exists, returns similar (fuzzy trigram — typos, transpositions, prefix-as-you-type) matches instead. Results are then ordered by relevance, then pinned status, then name; each result's `search_match_type` is `exact` or `similar`. When omitted, dashboards are ordered by pinned status then alphabetical name. Capped at 200 characters; longer queries return a 400 error."
        ),
})

export const DashboardsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DashboardsCreateQueryParams = () => zod.object({
    format: zod.enum(['json', 'txt']).optional(),
    include_dashboards: zod
        .boolean()
        .optional()
        .describe(
            'Opt in to receiving the deprecated `dashboards` field in insight payloads. Once opt-in enforcement is enabled, API-token callers stop receiving it by default; use `dashboard_tiles` instead.'
        ),
})

export const dashboardsCreateBodyNameMax = 400

export const dashboardsCreateBodyBreakdownColorsItemColorTokenRegExp = new RegExp('^preset-[1-9][0-9]\*$')
export const dashboardsCreateBodyGroupTitlesMaxOne = 200

export const dashboardsCreateBodyDeleteInsightsDefault = false

export const DashboardsCreateBody = () => zod
    .object({
        name: zod.string().max(dashboardsCreateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        breakdown_colors: zod
            .array(
                zod.object({
                    breakdownValue: zod
                        .string()
                        .describe('The breakdown value this color applies to, as it appears in the chart legend.'),
                    colorToken: zod
                        .string()
                        .regex(dashboardsCreateBodyBreakdownColorsItemColorTokenRegExp)
                        .nullable()
                        .describe(
                            'Palette slot to color the value with, as `preset-1` upwards. Not a CSS color: a hex value is rejected. Null leaves the value on its default color.'
                        ),
                    breakdownType: zod
                        .string()
                        .nullish()
                        .describe(
                            'Breakdown type the value came from, such as `event`, `person`, `session`, or `cohort`.'
                        ),
                    breakdownProperty: zod
                        .string()
                        .nullish()
                        .describe(
                            'Breakdown property the color is scoped to, so the color applies only to tiles that break down by that property. Omit to apply it under every property.'
                        ),
                    source: zod
                        .union([
                            zod.enum(['auto', 'manual']).describe('\* `auto` - auto\n\* `manual` - manual'),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            '`manual` for a color a person picked, `auto` for one the dashboard assigned.\n\n\* `auto` - auto\n\* `manual` - manual'
                        ),
                })
            )
            .nullish()
            .describe(
                "Colors pinned to specific breakdown values across the dashboard's tiles. A list of entries, not an object keyed by breakdown value. Send an empty list to clear them."
            ),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        grid_spacing: zod
            .enum(['tight', 'condensed', 'standard', 'relaxed', 'wide'])
            .describe(
                '\* `tight` - tight\n\* `condensed` - condensed\n\* `standard` - standard\n\* `relaxed` - relaxed\n\* `wide` - wide'
            )
            .optional()
            .describe(
                'Named tile density preset. Use tight, condensed, standard, relaxed, or wide.\n\n\* `tight` - tight\n\* `condensed` - condensed\n\* `standard` - standard\n\* `relaxed` - relaxed\n\* `wide` - wide'
            ),
        layout_compaction: zod
            .enum(['vertical', 'horizontal', 'stable'])
            .describe('\* `vertical` - vertical\n\* `horizontal` - horizontal\n\* `stable` - stable')
            .optional()
            .describe(
                'How tiles rearrange after a move or resize. vertical stacks tiles upward, horizontal stacks tiles to the left, and stable preserves positions while moving colliding tiles.\n\n\* `vertical` - vertical\n\* `horizontal` - horizontal\n\* `stable` - stable'
            ),
        group_titles: zod
            .record(zod.string(), zod.string().max(dashboardsCreateBodyGroupTitlesMaxOne))
            .nullish()
            .describe(
                "Titles for tile groups, keyed by the tiles' group_key. The dashboard shows a title above its group. A write replaces the whole map. Send an empty object or null to remove all group titles."
            ),
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

export const DashboardsRetrieveParams = () => zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DashboardsRetrieveQueryParams = () => zod.object({
    filters_override: zod
        .string()
        .optional()
        .describe(
            'Object (or pre-encoded JSON string) to override dashboard filters for this request only (not persisted). Top-level keys replace; nested values are not deep-merged — pass the complete value for any key you override. Accepts the same keys as the dashboard filters schema (e.g., `date_from`, `date_to`, `properties`). Ignored when accessed via a sharing token.'
        ),
    format: zod.enum(['json', 'txt']).optional(),
    include_dashboards: zod
        .boolean()
        .optional()
        .describe(
            'Opt in to receiving the deprecated `dashboards` field in insight payloads. Once opt-in enforcement is enabled, API-token callers stop receiving it by default; use `dashboard_tiles` instead.'
        ),
    variables_override: zod
        .string()
        .optional()
        .describe(
            'Object (or pre-encoded JSON string) to override dashboard variables for this request only (not persisted). Format: {\"<variable_id>\": {\"code_name\": \"<code_name>\", \"variableId\": \"<variable_id>\", \"value\": <new_value>}}. Each entry must include `code_name` — partial entries are silently dropped. The simplest workflow is to call `dashboard-get` first, copy the matching entry from the response, and mutate `value`. Top-level keys replace; nested values are not deep-merged. Ignored when accessed via a sharing token.'
        ),
})

export const DashboardsPartialUpdateParams = () => zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DashboardsPartialUpdateQueryParams = () => zod.object({
    format: zod.enum(['json', 'txt']).optional(),
    include_dashboards: zod
        .boolean()
        .optional()
        .describe(
            'Opt in to receiving the deprecated `dashboards` field in insight payloads. Once opt-in enforcement is enabled, API-token callers stop receiving it by default; use `dashboard_tiles` instead.'
        ),
})

export const dashboardsPartialUpdateBodyNameMax = 400

export const dashboardsPartialUpdateBodyBreakdownColorsItemColorTokenRegExp = new RegExp('^preset-[1-9][0-9]\*$')
export const dashboardsPartialUpdateBodyGroupTitlesMaxOne = 200

export const dashboardsPartialUpdateBodyTilesItemLayoutsOneSmOneXMin = 0
export const dashboardsPartialUpdateBodyTilesItemLayoutsOneSmOneXMax = 11

export const dashboardsPartialUpdateBodyTilesItemLayoutsOneSmOneYMin = 0

export const dashboardsPartialUpdateBodyTilesItemLayoutsOneSmOneWMax = 12

export const dashboardsPartialUpdateBodyTilesItemLayoutsOneXsOneXMin = 0
export const dashboardsPartialUpdateBodyTilesItemLayoutsOneXsOneXMax = 11

export const dashboardsPartialUpdateBodyTilesItemLayoutsOneXsOneYMin = 0

export const dashboardsPartialUpdateBodyTilesItemLayoutsOneXsOneWMax = 12

export const dashboardsPartialUpdateBodyTilesItemGroupKeyMax = 100

export const DashboardsPartialUpdateBody = () => zod
    .object({
        name: zod.string().max(dashboardsPartialUpdateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        filters: zod
            .object({
                date_from: zod
                    .string()
                    .nullish()
                    .describe(
                        "Dashboard-level start of the date range, e.g. '-30d', '-7d', or an ISO date. Applies to all tiles."
                    ),
                date_to: zod
                    .string()
                    .nullish()
                    .describe(
                        "Dashboard-level end of the date range, e.g. '-1d' or an ISO date. Null\/omitted means up to now."
                    ),
                properties: zod
                    .unknown()
                    .optional()
                    .describe(
                        'Dashboard-level property filters applied to every tile (PostHog property filter group).'
                    ),
            })
            .describe(
                "OpenAPI-only shape for a dashboard's filters object (agents\/MCP).\n\nDocuments the dashboard-level filters that act as the single source of truth for the\ndashboard's tiles. Runtime persistence reads the raw ``filters`` dict from the request body, so\nextra keys are accepted, but these are the ones agents should set."
            )
            .optional()
            .describe(
                'Dashboard-level filters (date range and properties) applied across all tiles as the source of truth.'
            ),
        breakdown_colors: zod
            .array(
                zod.object({
                    breakdownValue: zod
                        .string()
                        .describe('The breakdown value this color applies to, as it appears in the chart legend.'),
                    colorToken: zod
                        .string()
                        .regex(dashboardsPartialUpdateBodyBreakdownColorsItemColorTokenRegExp)
                        .nullable()
                        .describe(
                            'Palette slot to color the value with, as `preset-1` upwards. Not a CSS color: a hex value is rejected. Null leaves the value on its default color.'
                        ),
                    breakdownType: zod
                        .string()
                        .nullish()
                        .describe(
                            'Breakdown type the value came from, such as `event`, `person`, `session`, or `cohort`.'
                        ),
                    breakdownProperty: zod
                        .string()
                        .nullish()
                        .describe(
                            'Breakdown property the color is scoped to, so the color applies only to tiles that break down by that property. Omit to apply it under every property.'
                        ),
                    source: zod
                        .union([
                            zod.enum(['auto', 'manual']).describe('\* `auto` - auto\n\* `manual` - manual'),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            '`manual` for a color a person picked, `auto` for one the dashboard assigned.\n\n\* `auto` - auto\n\* `manual` - manual'
                        ),
                })
            )
            .nullish()
            .describe(
                "Colors pinned to specific breakdown values across the dashboard's tiles. A list of entries, not an object keyed by breakdown value. Send an empty list to clear them."
            ),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.string()).optional(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard.'),
        grid_spacing: zod
            .enum(['tight', 'condensed', 'standard', 'relaxed', 'wide'])
            .describe(
                '\* `tight` - tight\n\* `condensed` - condensed\n\* `standard` - standard\n\* `relaxed` - relaxed\n\* `wide` - wide'
            )
            .optional()
            .describe(
                'Named tile density preset. Use tight, condensed, standard, relaxed, or wide.\n\n\* `tight` - tight\n\* `condensed` - condensed\n\* `standard` - standard\n\* `relaxed` - relaxed\n\* `wide` - wide'
            ),
        layout_compaction: zod
            .enum(['vertical', 'horizontal', 'stable'])
            .describe('\* `vertical` - vertical\n\* `horizontal` - horizontal\n\* `stable` - stable')
            .optional()
            .describe(
                'How tiles rearrange after a move or resize. vertical stacks tiles upward, horizontal stacks tiles to the left, and stable preserves positions while moving colliding tiles.\n\n\* `vertical` - vertical\n\* `horizontal` - horizontal\n\* `stable` - stable'
            ),
        group_titles: zod
            .record(zod.string(), zod.string().max(dashboardsPartialUpdateBodyGroupTitlesMaxOne))
            .nullish()
            .describe(
                "Titles for tile groups, keyed by the tiles' group_key. The dashboard shows a title above its group. A write replaces the whole map. Send an empty object or null to remove all group titles."
            ),
        tiles: zod
            .array(
                zod.object({
                    id: zod.number().optional().describe('Dashboard tile ID to update.'),
                    layouts: zod
                        .object({
                            sm: zod
                                .object({
                                    x: zod
                                        .number()
                                        .min(dashboardsPartialUpdateBodyTilesItemLayoutsOneSmOneXMin)
                                        .max(dashboardsPartialUpdateBodyTilesItemLayoutsOneSmOneXMax)
                                        .describe('Column position in the dashboard grid (0-indexed).'),
                                    y: zod
                                        .number()
                                        .min(dashboardsPartialUpdateBodyTilesItemLayoutsOneSmOneYMin)
                                        .describe('Row position in the dashboard grid (0-indexed).'),
                                    w: zod
                                        .number()
                                        .min(1)
                                        .max(dashboardsPartialUpdateBodyTilesItemLayoutsOneSmOneWMax)
                                        .describe('Width in grid columns. The desktop grid is 12 columns wide.'),
                                    h: zod.number().min(1).describe('Height in grid rows.'),
                                })
                                .describe(
                                    "Layout for the standard (desktop) breakpoint. The grid is 12 columns wide. A write replaces the tile's whole layout and the dashboard reads desktop placement from this box, so send it whenever you send layouts."
                                ),
                            xs: zod
                                .object({
                                    x: zod
                                        .number()
                                        .min(dashboardsPartialUpdateBodyTilesItemLayoutsOneXsOneXMin)
                                        .max(dashboardsPartialUpdateBodyTilesItemLayoutsOneXsOneXMax)
                                        .describe('Column position in the dashboard grid (0-indexed).'),
                                    y: zod
                                        .number()
                                        .min(dashboardsPartialUpdateBodyTilesItemLayoutsOneXsOneYMin)
                                        .describe('Row position in the dashboard grid (0-indexed).'),
                                    w: zod
                                        .number()
                                        .min(1)
                                        .max(dashboardsPartialUpdateBodyTilesItemLayoutsOneXsOneWMax)
                                        .describe('Width in grid columns. The desktop grid is 12 columns wide.'),
                                    h: zod.number().min(1).describe('Height in grid rows.'),
                                })
                                .optional()
                                .describe(
                                    'Layout for the small (mobile) breakpoint, on a 1-column grid. The dashboard derives this layout from the sm order and heights, so a stored xs box does not change what renders.'
                                ),
                        })
                        .optional()
                        .describe(
                            "Grid position and size per breakpoint. Works for every tile type, including insight tiles. A write replaces the tile's whole layout, so send a complete sm box rather than the one value you want to change. Boxes are stored as sent and overlaps are not resolved, so send sm boxes that do not overlap, and include every tile you move in the same request."
                        ),
                    show_description: zod
                        .boolean()
                        .optional()
                        .describe(
                            "Whether to show the tile's description underneath its title on the dashboard. Works for every tile type. The description itself is unaffected and still comes from the tile's insight, text, or widget content — this only toggles whether it renders on the dashboard."
                        ),
                    group_key: zod
                        .string()
                        .max(dashboardsPartialUpdateBodyTilesItemGroupKeyMax)
                        .nullish()
                        .describe(
                            "Key that puts this tile in a group with the other tiles that have the same key on this dashboard. Set the group's title in the dashboard's group_titles. Null or an empty string removes the tile from its group."
                        ),
                    badge: zod
                        .union([
                            zod
                                .enum(['winner', 'cheeky-hog'])
                                .describe('\* `winner` - Winner\n\* `cheeky-hog` - Cheeky hog'),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            'Badge on the tile. winner shows a crown in the top left corner, for example to mark the best tile in a group. cheeky-hog shows a hedgehog when a person hovers over the tile. Null removes the badge. More than one tile in a group can have the winner badge.\n\n\* `winner` - Winner\n\* `cheeky-hog` - Cheeky hog'
                        ),
                })
            )
            .optional()
            .describe(
                'Dashboard tiles to update, each identified by its tile id. Any tile type accepts `layouts` to set its grid position and size. Widget tiles also accept nested widget.config patches.'
            ),
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
    .describe(
        'OpenAPI-only PATCH body for dashboards (agents\/MCP).\n\nMust be a superset of ``dashboard_patch_runtime_openapi_field_names()`` — ``extend_schema(request=...)``\nreplaces the inferred schema entirely. Contract: ``test_dashboard_openapi.py``.'
    )

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const DashboardsDestroyParams = () => zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DashboardsDestroyQueryParams = () => zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

/**
 * Copy an existing dashboard tile to another dashboard (insight, text card, or widget tile).
 */
export const DashboardsCopyTileCreateParams = () => zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DashboardsCopyTileCreateQueryParams = () => zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const DashboardsCopyTileCreateBody = () => zod.object({
    fromDashboardId: zod.number().describe('Dashboard id the tile currently belongs to.'),
    tileId: zod.number().describe('Dashboard tile id to copy.'),
})

/**
 * Add a markdown text tile to a dashboard.
 *
 * Text tiles render as markdown blocks on the dashboard — useful as section headings, dividers,
 * or annotations between insight tiles to give the dashboard structure.
 */
export const DashboardsCreateTextTileCreateParams = () => zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DashboardsCreateTextTileCreateQueryParams = () => zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const dashboardsCreateTextTileCreateBodyTypeDefault = `text`
export const dashboardsCreateTextTileCreateBodyBodyMax = 4000

export const dashboardsCreateTextTileCreateBodyAgentContextMax = 10000

export const dashboardsCreateTextTileCreateBodyColorMax = 400

export const DashboardsCreateTextTileCreateBody = () => zod.object({
    type: zod
        .enum(['text', 'image'])
        .describe('\* `text` - text\n\* `image` - image')
        .default(dashboardsCreateTextTileCreateBodyTypeDefault)
        .describe(
            'Tile type. Use image for a body with exactly one Markdown image. Defaults to text.\n\n\* `text` - text\n\* `image` - image'
        ),
    body: zod
        .string()
        .min(1)
        .max(dashboardsCreateTextTileCreateBodyBodyMax)
        .describe(
            'Markdown body for the dashboard tile. Text tiles support headings, lists, and inline formatting. Image tiles require exactly one Markdown image. Max 4000 characters.'
        ),
    agent_context: zod
        .string()
        .max(dashboardsCreateTextTileCreateBodyAgentContextMax)
        .nullish()
        .describe(
            "Optional context that helps AI agents make consistent dashboard updates, such as Data Catalog metric names, data sources, tile-specific query assumptions, caveats, or editing guidance. PostHog's Data Catalog is the semantic layer. Store canonical metric definitions there, not in this field. An empty string or null means there is no agent context. Shared and exported dashboards, and organizations without AI data processing approval, omit this field. Max 10000 characters."
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
 *
 * Works for text, insight, and button tiles. The underlying Insight, Text, or ButtonTile
 * object is preserved — only the dashboard tile is hidden. To delete the entire dashboard,
 * use the dashboard delete endpoint instead.
 */
export const DashboardsDeleteTileParams = () => zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DashboardsDeleteTileQueryParams = () => zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const DashboardsDeleteTileBody = () => zod.object({
    tile_id: zod.number().describe('ID of the dashboard tile to delete. Use dashboard-get to look up tile IDs.'),
})

export const DashboardsMoveTilePartialUpdateParams = () => zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DashboardsMoveTilePartialUpdateQueryParams = () => zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const DashboardsMoveTilePartialUpdateBody = () => zod.object({
    to_dashboard: zod.number().optional().describe('Destination dashboard ID.'),
    tile: zod
        .object({
            id: zod.number().describe('Dashboard tile ID to move.'),
        })
        .optional()
        .describe('Tile to move, identified by its dashboard tile ID.'),
})

export const DashboardsReorderTilesCreateParams = () => zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DashboardsReorderTilesCreateQueryParams = () => zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const dashboardsReorderTilesCreateBodyLayoutDefault = `preserve`

export const DashboardsReorderTilesCreateBody = () => zod.object({
    tile_order: zod
        .array(zod.number())
        .min(1)
        .describe('Array of tile IDs in the desired display order (top to bottom, left to right).'),
    layout: zod
        .enum(['preserve', 'two_column', 'three_column', 'full_width'])
        .describe(
            '\* `preserve` - preserve\n\* `two_column` - two_column\n\* `three_column` - three_column\n\* `full_width` - full_width'
        )
        .default(dashboardsReorderTilesCreateBodyLayoutDefault)
        .describe(
            "How to size tiles when reordering. 'preserve' (default) keeps each tile's existing width and height and only repacks positions in the new order. Use the other modes only when every tile should use the same size: 'two_column' makes every tile 6-wide × 5-tall, 'three_column' makes every tile 4-wide × 5-tall, and 'full_width' makes every tile 12-wide × 5-tall.\n\n\* `preserve` - preserve\n\* `two_column` - two_column\n\* `three_column` - three_column\n\* `full_width` - full_width"
        ),
})

/**
 * Run all insights on a dashboard and return their results.
 */
export const DashboardsRunInsightsRetrieveParams = () => zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DashboardsRunInsightsRetrieveQueryParams = () => zod.object({
    filters_override: zod
        .string()
        .optional()
        .describe(
            'Object (or pre-encoded JSON string) to override dashboard filters for this request only (not persisted). Top-level keys replace; nested values are not deep-merged — pass the complete value for any key you override. Accepts the same keys as the dashboard filters schema (e.g., `date_from`, `date_to`, `properties`). Ignored when accessed via a sharing token.'
        ),
    format: zod.enum(['json', 'txt']).optional(),
    max_result_chars: zod
        .number()
        .optional()
        .describe(
            "Per-tile character budget for 'optimized' output, truncation marker included. A longer table keeps its header and both ends, and names how many rows were dropped from the middle. Defaults to 2000; pass 0 for the whole table, or 200 or more, since a smaller budget cannot carry the marker. Ignored when output_format is 'json'. Any value above zero is also held down to what the response has left of its 30000 character budget, and tiles past that budget are not run."
        ),
    output_format: zod
        .enum(['json', 'optimized'])
        .optional()
        .describe(
            "'optimized' (default) returns LLM-friendly formatted text per insight, bounded by max_result_chars. 'json' returns the raw query result objects, unbounded."
        ),
    refresh: zod
        .enum(['blocking', 'force_blocking', 'force_cache'])
        .optional()
        .describe(
            "Cache behavior. 'force_cache' (default) serves from cache even if stale. 'blocking' uses cache if fresh, otherwise recalculates. 'force_blocking' always recalculates."
        ),
    tile_ids: zod
        .string()
        .optional()
        .describe(
            'Comma-separated dashboard tile IDs to run. Defaults to every insight tile on the dashboard. Use it to read one tile without receiving the others. An ID that is not on this dashboard is rejected.'
        ),
    variables_override: zod
        .string()
        .optional()
        .describe(
            'Object (or pre-encoded JSON string) to override dashboard variables for this request only (not persisted). Format: {\"<variable_id>\": {\"code_name\": \"<code_name>\", \"variableId\": \"<variable_id>\", \"value\": <new_value>}}. Each entry must include `code_name` — partial entries are silently dropped. The simplest workflow is to call `dashboard-get` first, copy the matching entry from the response, and mutate `value`. Top-level keys replace; nested values are not deep-merged. Ignored when accessed via a sharing token.'
        ),
})

export const DashboardsRunWidgetsRetrieveParams = () => zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DashboardsRunWidgetsRetrieveQueryParams = () => zod.object({
    format: zod.enum(['json', 'txt']).optional(),
    tile_ids: zod.string().describe('Comma-separated dashboard tile IDs to run widgets for.'),
})

/**
 * Update the markdown body, layout, or color of an existing text tile on a dashboard.
 */
export const DashboardsUpdateTextTileCreateParams = () => zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DashboardsUpdateTextTileCreateQueryParams = () => zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const dashboardsUpdateTextTileCreateBodyBodyMax = 4000

export const dashboardsUpdateTextTileCreateBodyAgentContextMax = 10000

export const dashboardsUpdateTextTileCreateBodyColorMax = 400

export const DashboardsUpdateTextTileCreateBody = () => zod.object({
    tile_id: zod.number().describe('ID of the dashboard tile to update. Use dashboard-get to look up tile IDs.'),
    body: zod
        .string()
        .min(1)
        .max(dashboardsUpdateTextTileCreateBodyBodyMax)
        .optional()
        .describe('New markdown body for the text tile. Omit to leave the body unchanged. Max 4000 characters.'),
    agent_context: zod
        .string()
        .max(dashboardsUpdateTextTileCreateBodyAgentContextMax)
        .nullish()
        .describe(
            "Optional context that helps AI agents make consistent dashboard updates, such as Data Catalog metric names, data sources, tile-specific query assumptions, caveats, or editing guidance. PostHog's Data Catalog is the semantic layer. Store canonical metric definitions there, not in this field. An empty string or null means there is no agent context. Shared and exported dashboards, and organizations without AI data processing approval, omit this field. Max 10000 characters."
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
export const DashboardsWidgetsBatchCreateParams = () => zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DashboardsWidgetsBatchCreateQueryParams = () => zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const dashboardsWidgetsBatchCreateBodyWidgetsItemNameMax = 400

export const dashboardsWidgetsBatchCreateBodyWidgetsMax = 10

export const DashboardsWidgetsBatchCreateBody = () => zod
    .object({
        widgets: zod
            .array(
                zod.object({
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
                                .describe('Layout for the standard (desktop) breakpoint. The grid is 12 columns wide.'),
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
                                .describe(
                                    'Layout for the small (mobile) breakpoint, on a 1-column grid. The dashboard derives this layout from the sm order and heights, so a stored xs box does not change what renders.'
                                ),
                        })
                        .optional()
                        .describe('Optional react-grid-layout positions keyed by breakpoint (sm, xs).'),
                    show_description: zod
                        .boolean()
                        .optional()
                        .describe('Whether to show the description on the dashboard tile.'),
                    widget_type: zod
                        .enum([
                            'activity_events_list',
                            'canvas_app',
                            'conversations_recent_tickets',
                            'error_tracking_list',
                            'experiment_results',
                            'experiments_list',
                            'logs_list',
                            'notebook_widget',
                            'session_replay_list',
                            'survey_results',
                        ])
                        .describe(
                            '\* `activity_events_list` - Activity Events List\n\* `canvas_app` - Canvas App\n\* `conversations_recent_tickets` - Conversations Recent Tickets\n\* `error_tracking_list` - Error Tracking List\n\* `experiment_results` - Experiment Results\n\* `experiments_list` - Experiments List\n\* `logs_list` - Logs List\n\* `notebook_widget` - Notebook Widget\n\* `session_replay_list` - Session Replay List\n\* `survey_results` - Survey Results'
                        )
                        .describe(
                            'Widget type to add. Use dashboard-widget-catalog-list to pick one.\n\n\* `activity_events_list` - Activity Events List\n\* `canvas_app` - Canvas App\n\* `conversations_recent_tickets` - Conversations Recent Tickets\n\* `error_tracking_list` - Error Tracking List\n\* `experiment_results` - Experiment Results\n\* `experiments_list` - Experiments List\n\* `logs_list` - Logs List\n\* `notebook_widget` - Notebook Widget\n\* `session_replay_list` - Session Replay List\n\* `survey_results` - Survey Results'
                        ),
                    config: zod
                        .record(zod.string(), zod.unknown())
                        .describe(
                            "Widget configuration as a JSON object. Its keys depend on widget_type: read that type's config_schema from dashboard-widget-catalog-list. The API validates the config and returns a 400 that names each invalid field."
                        ),
                })
            )
            .min(1)
            .max(dashboardsWidgetsBatchCreateBodyWidgetsMax)
            .describe(
                'Widget tiles to add atomically. Supported widget_type values: activity_events_list, canvas_app, conversations_recent_tickets, error_tracking_list, experiment_results, experiments_list, logs_list, notebook_widget, session_replay_list, survey_results. Use dashboard-widget-catalog-list for per-type config_schema documentation. (1–10 per request).'
            ),
    })
    .describe('OpenAPI-only batch-add schema with widget_type-discriminated config shapes for agents.')

/**
 * Update the settings of existing widgets in place, atomically — config, name, and description.
 *
 * Each entry targets a widget by its tile_id and reuses the same write path as the dashboard PATCH endpoint.
 * The widget_type is immutable. This edits widget settings only (config, name, description); tile placement
 * (layouts, show_description) is a dashboard concern — use the dashboard PATCH endpoint or reorder_tiles for
 * that. All updates succeed or fail together. To add new widgets, use the widgets/batch POST endpoint; to
 * remove one, use delete_tile.
 */
export const DashboardsUpdateWidgetsBatchParams = () => zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DashboardsUpdateWidgetsBatchQueryParams = () => zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const dashboardsUpdateWidgetsBatchBodyWidgetsItemNameMax = 400

export const dashboardsUpdateWidgetsBatchBodyWidgetsMax = 10

export const DashboardsUpdateWidgetsBatchBody = () => zod
    .object({
        widgets: zod
            .array(
                zod.object({
                    tile_id: zod
                        .number()
                        .describe('ID of the widget tile to update. Use dashboard-get to look up widget tile IDs.'),
                    name: zod
                        .string()
                        .max(dashboardsUpdateWidgetsBatchBodyWidgetsItemNameMax)
                        .nullish()
                        .describe(
                            'New display name for the widget. Empty string or null clears it; omit to leave unchanged.'
                        ),
                    description: zod
                        .string()
                        .optional()
                        .describe('New markdown description for the widget. Omit to leave unchanged.'),
                    widget_type: zod
                        .enum([
                            'activity_events_list',
                            'canvas_app',
                            'conversations_recent_tickets',
                            'error_tracking_list',
                            'experiment_results',
                            'experiments_list',
                            'logs_list',
                            'notebook_widget',
                            'session_replay_list',
                            'survey_results',
                        ])
                        .describe(
                            '\* `activity_events_list` - Activity Events List\n\* `canvas_app` - Canvas App\n\* `conversations_recent_tickets` - Conversations Recent Tickets\n\* `error_tracking_list` - Error Tracking List\n\* `experiment_results` - Experiment Results\n\* `experiments_list` - Experiments List\n\* `logs_list` - Logs List\n\* `notebook_widget` - Notebook Widget\n\* `session_replay_list` - Session Replay List\n\* `survey_results` - Survey Results'
                        )
                        .optional()
                        .describe(
                            "The tile's widget type. It cannot be changed, so omit it or pass the current type.\n\n\* `activity_events_list` - Activity Events List\n\* `canvas_app` - Canvas App\n\* `conversations_recent_tickets` - Conversations Recent Tickets\n\* `error_tracking_list` - Error Tracking List\n\* `experiment_results` - Experiment Results\n\* `experiments_list` - Experiments List\n\* `logs_list` - Logs List\n\* `notebook_widget` - Notebook Widget\n\* `session_replay_list` - Session Replay List\n\* `survey_results` - Survey Results"
                        ),
                    config: zod
                        .record(zod.string(), zod.unknown())
                        .optional()
                        .describe(
                            "Widget configuration as a JSON object. Its keys depend on widget_type: read that type's config_schema from dashboard-widget-catalog-list. The API validates the config and returns a 400 that names each invalid field. Each top-level key you send replaces the stored value, and keys you leave out stay as they are. Omit config to leave it unchanged."
                        ),
                })
            )
            .min(1)
            .max(dashboardsUpdateWidgetsBatchBodyWidgetsMax)
            .optional()
            .describe(
                'Widget tiles to update atomically, each identified by its tile_id. config shape is per widget_type; see dashboard-widget-catalog-list for per-type config_schema (1–10 per request).'
            ),
    })
    .describe('OpenAPI-only batch-update schema with widget_type-discriminated config shapes for agents.')

/**
 * Soft-delete up to 100 dashboards. Optionally delete insights with no remaining dashboard. Report missing or inaccessible dashboards as skipped.
 */
export const DashboardsBulkDeleteCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const dashboardsBulkDeleteCreateBodyIdsMax = 100

export const dashboardsBulkDeleteCreateBodyDeleteInsightsDefault = false

export const DashboardsBulkDeleteCreateBody = () => zod.object({
    ids: zod
        .array(zod.number().min(1))
        .max(dashboardsBulkDeleteCreateBodyIdsMax)
        .describe('Dashboard IDs to soft-delete. At most 100 IDs per request.'),
    delete_insights: zod
        .boolean()
        .default(dashboardsBulkDeleteCreateBodyDeleteInsightsDefault)
        .describe('Also delete insights that have no remaining dashboard after deletion. Defaults to false.'),
})

/**
 * List registered dashboard widget types and per-type config_schema documentation for agents.
 */
export const DashboardsWidgetCatalogRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DashboardsWidgetCatalogRetrieveQueryParams = () => zod.object({
    format: zod.enum(['json', 'txt']).optional(),
    widget_type: zod
        .array(
            zod.enum([
                'activity_events_list',
                'canvas_app',
                'conversations_recent_tickets',
                'error_tracking_list',
                'experiment_results',
                'experiments_list',
                'logs_list',
                'notebook_widget',
                'session_replay_list',
                'survey_results',
            ])
        )
        .optional()
        .describe('Widget types to return. Omit to return every registered widget type.'),
})
