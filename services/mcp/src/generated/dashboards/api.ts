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
    folder: zod
        .string()
        .optional()
        .describe(
            "Optional. Return only dashboards filed directly in this project-tree folder, e.g. 'Unfiled/Dashboards'. An empty string matches dashboards at the project root. Nested sub-folders are not included."
        ),
    format: zod.enum(['json', 'txt']).optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod
        .string()
        .optional()
        .describe(
            "Optional. Match against dashboard `name`, `description`, and tag names. Returns case-insensitive substring matches and fuzzy trigram matches (typos, transpositions, prefix-as-you-type) together, ordered exact-first, then pinned status, then name; each result's `search_match_type` is `exact` or `similar`. When omitted, dashboards are ordered by pinned status then alphabetical name. Capped at 200 characters; longer queries return a 400 error."
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

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneLimitDefault = 25
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneLimitMax = 50

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoLimitDefault = 10
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoLimitMax = 25

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoOrderByDefault = `occurrences`
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoOrderDirectionDefault = `DESC`
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoStatusDefault = `active`

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneThreeLimitDefault = 10
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneThreeLimitMax = 25

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneThreeOrderByDefault = `start_time`
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneThreeOrderDirectionDefault = `DESC`
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFourLimitDefault = 10
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFourLimitMax = 25

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFourOrderByDefault = `created_at`
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFourOrderDirectionDefault = `DESC`
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFourStatusDefault = `all`
export const dashboardsPartialUpdateBodyTilesItemWidgetOneNameMax = 400

export const DashboardsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsPartialUpdateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.string()).optional(),
        restriction_level: zod.union([zod.literal(21), zod.literal(37)]).optional(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard.'),
        tiles: zod
            .array(
                zod.object({
                    id: zod.number().optional().describe('Dashboard tile ID to update.'),
                    widget: zod
                        .object({
                            id: zod
                                .string()
                                .optional()
                                .describe('Existing widget row ID when updating a widget tile via dashboard PATCH.'),
                            widget_type: zod
                                .enum([
                                    'activity_events_list',
                                    'error_tracking_list',
                                    'experiment_results',
                                    'experiments_list',
                                    'session_replay_list',
                                ])
                                .describe(
                                    '* `activity_events_list` - activity_events_list\n* `error_tracking_list` - error_tracking_list\n* `experiment_results` - experiment_results\n* `experiments_list` - experiments_list\n* `session_replay_list` - session_replay_list'
                                )
                                .optional()
                                .describe(
                                    'Widget type identifier (cannot be changed on update).\n\n* `activity_events_list` - activity_events_list\n* `error_tracking_list` - error_tracking_list\n* `experiment_results` - experiment_results\n* `experiments_list` - experiments_list\n* `session_replay_list` - session_replay_list'
                                ),
                            config: zod
                                .union([
                                    zod.object({
                                        dateRange: zod
                                            .union([
                                                zod.object({
                                                    date_from: zod
                                                        .union([
                                                            zod.enum([
                                                                '-1M',
                                                                '-30M',
                                                                '-1h',
                                                                '-3h',
                                                                '-24h',
                                                                '-7d',
                                                                '-14d',
                                                                '-30d',
                                                                '-90d',
                                                            ]),
                                                            zod.null(),
                                                        ])
                                                        .optional(),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional(),
                                        filterTestAccounts: zod.union([zod.boolean(), zod.null()]).optional(),
                                        widgetFilters: zod
                                            .union([
                                                zod.record(
                                                    zod.string(),
                                                    zod.object({
                                                        filterId: zod.string().min(1),
                                                        propertyName: zod.string().min(1),
                                                        optionId: zod.string().min(1),
                                                        operator: zod.enum([
                                                            'exact',
                                                            'is_not',
                                                            'icontains',
                                                            'not_icontains',
                                                            'regex',
                                                            'not_regex',
                                                            'gt',
                                                            'gte',
                                                            'lt',
                                                            'lte',
                                                            'is_set',
                                                            'is_not_set',
                                                            'is_date_exact',
                                                            'is_date_before',
                                                            'is_date_after',
                                                            'between',
                                                            'not_between',
                                                            'min',
                                                            'max',
                                                            'in',
                                                            'not_in',
                                                            'is_cleaned_path_exact',
                                                            'flag_evaluates_to',
                                                            'semver_eq',
                                                            'semver_neq',
                                                            'semver_gt',
                                                            'semver_gte',
                                                            'semver_lt',
                                                            'semver_lte',
                                                            'semver_tilde',
                                                            'semver_caret',
                                                            'semver_wildcard',
                                                            'icontains_multi',
                                                            'not_icontains_multi',
                                                        ]),
                                                        value: zod
                                                            .union([zod.string(), zod.array(zod.string()), zod.null()])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional(),
                                        limit: zod
                                            .number()
                                            .min(1)
                                            .max(dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneLimitMax)
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneLimitDefault
                                            )
                                            .describe('Maximum number of events to return.'),
                                    }),
                                    zod.object({
                                        dateRange: zod
                                            .union([
                                                zod.object({
                                                    date_from: zod
                                                        .union([
                                                            zod.enum([
                                                                '-1M',
                                                                '-30M',
                                                                '-1h',
                                                                '-3h',
                                                                '-24h',
                                                                '-7d',
                                                                '-14d',
                                                                '-30d',
                                                                '-90d',
                                                            ]),
                                                            zod.null(),
                                                        ])
                                                        .optional(),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional(),
                                        filterTestAccounts: zod.union([zod.boolean(), zod.null()]).optional(),
                                        widgetFilters: zod
                                            .union([
                                                zod.record(
                                                    zod.string(),
                                                    zod.object({
                                                        filterId: zod.string().min(1),
                                                        propertyName: zod.string().min(1),
                                                        optionId: zod.string().min(1),
                                                        operator: zod.enum([
                                                            'exact',
                                                            'is_not',
                                                            'icontains',
                                                            'not_icontains',
                                                            'regex',
                                                            'not_regex',
                                                            'gt',
                                                            'gte',
                                                            'lt',
                                                            'lte',
                                                            'is_set',
                                                            'is_not_set',
                                                            'is_date_exact',
                                                            'is_date_before',
                                                            'is_date_after',
                                                            'between',
                                                            'not_between',
                                                            'min',
                                                            'max',
                                                            'in',
                                                            'not_in',
                                                            'is_cleaned_path_exact',
                                                            'flag_evaluates_to',
                                                            'semver_eq',
                                                            'semver_neq',
                                                            'semver_gt',
                                                            'semver_gte',
                                                            'semver_lt',
                                                            'semver_lte',
                                                            'semver_tilde',
                                                            'semver_caret',
                                                            'semver_wildcard',
                                                            'icontains_multi',
                                                            'not_icontains_multi',
                                                        ]),
                                                        value: zod
                                                            .union([zod.string(), zod.array(zod.string()), zod.null()])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional(),
                                        limit: zod
                                            .number()
                                            .min(1)
                                            .max(dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoLimitMax)
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoLimitDefault
                                            )
                                            .describe('Maximum number of issues to return.'),
                                        orderBy: zod
                                            .enum(['last_seen', 'first_seen', 'occurrences', 'users', 'sessions'])
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoOrderByDefault
                                            )
                                            .describe('Issue ranking column.'),
                                        orderDirection: zod
                                            .enum(['ASC', 'DESC'])
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoOrderDirectionDefault
                                            )
                                            .describe('Sort direction for orderBy.'),
                                        status: zod
                                            .enum([
                                                'archived',
                                                'active',
                                                'resolved',
                                                'pending_release',
                                                'suppressed',
                                                'all',
                                            ])
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoStatusDefault
                                            )
                                            .describe('Issue status filter.'),
                                        assignee: zod
                                            .union([
                                                zod.object({
                                                    id: zod.union([zod.string(), zod.number()]),
                                                    type: zod.enum(['user', 'role']),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Filter by assignee ({type: user|role, id}). Omit for any assignee.'
                                            ),
                                    }),
                                    zod.object({
                                        dateRange: zod
                                            .union([
                                                zod.object({
                                                    date_from: zod
                                                        .union([
                                                            zod.enum([
                                                                '-1M',
                                                                '-30M',
                                                                '-1h',
                                                                '-3h',
                                                                '-24h',
                                                                '-7d',
                                                                '-14d',
                                                                '-30d',
                                                                '-90d',
                                                            ]),
                                                            zod.null(),
                                                        ])
                                                        .optional(),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional(),
                                        filterTestAccounts: zod.union([zod.boolean(), zod.null()]).optional(),
                                        widgetFilters: zod
                                            .union([
                                                zod.record(
                                                    zod.string(),
                                                    zod.object({
                                                        filterId: zod.string().min(1),
                                                        propertyName: zod.string().min(1),
                                                        optionId: zod.string().min(1),
                                                        operator: zod.enum([
                                                            'exact',
                                                            'is_not',
                                                            'icontains',
                                                            'not_icontains',
                                                            'regex',
                                                            'not_regex',
                                                            'gt',
                                                            'gte',
                                                            'lt',
                                                            'lte',
                                                            'is_set',
                                                            'is_not_set',
                                                            'is_date_exact',
                                                            'is_date_before',
                                                            'is_date_after',
                                                            'between',
                                                            'not_between',
                                                            'min',
                                                            'max',
                                                            'in',
                                                            'not_in',
                                                            'is_cleaned_path_exact',
                                                            'flag_evaluates_to',
                                                            'semver_eq',
                                                            'semver_neq',
                                                            'semver_gt',
                                                            'semver_gte',
                                                            'semver_lt',
                                                            'semver_lte',
                                                            'semver_tilde',
                                                            'semver_caret',
                                                            'semver_wildcard',
                                                            'icontains_multi',
                                                            'not_icontains_multi',
                                                        ]),
                                                        value: zod
                                                            .union([zod.string(), zod.array(zod.string()), zod.null()])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional(),
                                        limit: zod
                                            .number()
                                            .min(1)
                                            .max(dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneThreeLimitMax)
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneThreeLimitDefault
                                            )
                                            .describe('Maximum number of recordings to return.'),
                                        orderBy: zod
                                            .enum([
                                                'start_time',
                                                'activity_score',
                                                'recording_duration',
                                                'duration',
                                                'click_count',
                                                'console_error_count',
                                            ])
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneThreeOrderByDefault
                                            )
                                            .describe('Recording ranking column.'),
                                        orderDirection: zod
                                            .enum(['ASC', 'DESC'])
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneThreeOrderDirectionDefault
                                            )
                                            .describe('Sort direction for orderBy.'),
                                        savedFilterId: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                'short_id of a saved session replay filter to use as the recordings source. When set, the saved filter owns the date range and property filters; only orderBy, orderDirection, and limit still apply.'
                                            ),
                                    }),
                                    zod.object({
                                        limit: zod
                                            .number()
                                            .min(1)
                                            .max(dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFourLimitMax)
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFourLimitDefault
                                            )
                                            .describe('Maximum number of experiments to return.'),
                                        orderBy: zod
                                            .enum(['created_at', 'name', 'start_date'])
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFourOrderByDefault
                                            )
                                            .describe('Experiment list sort column.'),
                                        orderDirection: zod
                                            .enum(['ASC', 'DESC'])
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFourOrderDirectionDefault
                                            )
                                            .describe('Sort direction for orderBy.'),
                                        status: zod
                                            .enum(['draft', 'running', 'paused', 'stopped', 'all'])
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFourStatusDefault
                                            )
                                            .describe('Experiment status filter.'),
                                        createdBy: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Filter by creator (user id). Omit for any creator.'),
                                    }),
                                    zod.object({
                                        experimentId: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Experiment to show results for. Null until the user picks one in the widget settings.'
                                            ),
                                    }),
                                ])
                                .optional()
                                .describe("Widget-specific configuration. Shape depends on the tile's widget_type."),
                            name: zod
                                .string()
                                .max(dashboardsPartialUpdateBodyTilesItemWidgetOneNameMax)
                                .nullish()
                                .describe('Optional custom display name for the widget tile.'),
                            description: zod
                                .string()
                                .optional()
                                .describe('Optional markdown description shown when show_description is enabled.'),
                        })
                        .optional()
                        .describe('Nested widget row updates.'),
                })
            )
            .optional()
            .describe('Dashboard tiles to update. Widget tiles accept nested widget.config patches.'),
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
        'OpenAPI-only PATCH body for dashboards (agents/MCP).\n\nMust be a superset of ``dashboard_patch_runtime_openapi_field_names()`` — ``extend_schema(request=...)``\nreplaces the inferred schema entirely. Contract: ``test_dashboard_openapi.py``.'
    )

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
 *
 * Text tiles render as markdown blocks on the dashboard — useful as section headings, dividers,
 * or annotations between insight tiles to give the dashboard structure.
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
 *
 * Works for text, insight, and button tiles. The underlying Insight, Text, or ButtonTile
 * object is preserved — only the dashboard tile is hidden. To delete the entire dashboard,
 * use the dashboard delete endpoint instead.
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

export const dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneLimitDefault = 25
export const dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneLimitMax = 50

export const dashboardsWidgetsBatchCreateBodyWidgetsItemTwoNameMax = 400

export const dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneLimitDefault = 10
export const dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneLimitMax = 25

export const dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneOrderByDefault = `occurrences`
export const dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneOrderDirectionDefault = `DESC`
export const dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneStatusDefault = `active`
export const dashboardsWidgetsBatchCreateBodyWidgetsItemThreeNameMax = 400

export const dashboardsWidgetsBatchCreateBodyWidgetsItemThreeConfigOneLimitDefault = 10
export const dashboardsWidgetsBatchCreateBodyWidgetsItemThreeConfigOneLimitMax = 25

export const dashboardsWidgetsBatchCreateBodyWidgetsItemThreeConfigOneOrderByDefault = `start_time`
export const dashboardsWidgetsBatchCreateBodyWidgetsItemThreeConfigOneOrderDirectionDefault = `DESC`
export const dashboardsWidgetsBatchCreateBodyWidgetsItemFourNameMax = 400

export const dashboardsWidgetsBatchCreateBodyWidgetsItemFourConfigOneLimitDefault = 10
export const dashboardsWidgetsBatchCreateBodyWidgetsItemFourConfigOneLimitMax = 25

export const dashboardsWidgetsBatchCreateBodyWidgetsItemFourConfigOneOrderByDefault = `created_at`
export const dashboardsWidgetsBatchCreateBodyWidgetsItemFourConfigOneOrderDirectionDefault = `DESC`
export const dashboardsWidgetsBatchCreateBodyWidgetsItemFourConfigOneStatusDefault = `all`
export const dashboardsWidgetsBatchCreateBodyWidgetsItemFiveNameMax = 400

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
                        widget_type: zod.enum(['activity_events_list']),
                        config: zod
                            .object({
                                dateRange: zod
                                    .union([
                                        zod.object({
                                            date_from: zod
                                                .union([
                                                    zod.enum([
                                                        '-1M',
                                                        '-30M',
                                                        '-1h',
                                                        '-3h',
                                                        '-24h',
                                                        '-7d',
                                                        '-14d',
                                                        '-30d',
                                                        '-90d',
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .optional(),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional(),
                                filterTestAccounts: zod.union([zod.boolean(), zod.null()]).optional(),
                                widgetFilters: zod
                                    .union([
                                        zod.record(
                                            zod.string(),
                                            zod.object({
                                                filterId: zod.string().min(1),
                                                propertyName: zod.string().min(1),
                                                optionId: zod.string().min(1),
                                                operator: zod.enum([
                                                    'exact',
                                                    'is_not',
                                                    'icontains',
                                                    'not_icontains',
                                                    'regex',
                                                    'not_regex',
                                                    'gt',
                                                    'gte',
                                                    'lt',
                                                    'lte',
                                                    'is_set',
                                                    'is_not_set',
                                                    'is_date_exact',
                                                    'is_date_before',
                                                    'is_date_after',
                                                    'between',
                                                    'not_between',
                                                    'min',
                                                    'max',
                                                    'in',
                                                    'not_in',
                                                    'is_cleaned_path_exact',
                                                    'flag_evaluates_to',
                                                    'semver_eq',
                                                    'semver_neq',
                                                    'semver_gt',
                                                    'semver_gte',
                                                    'semver_lt',
                                                    'semver_lte',
                                                    'semver_tilde',
                                                    'semver_caret',
                                                    'semver_wildcard',
                                                    'icontains_multi',
                                                    'not_icontains_multi',
                                                ]),
                                                value: zod
                                                    .union([zod.string(), zod.array(zod.string()), zod.null()])
                                                    .optional(),
                                            })
                                        ),
                                        zod.null(),
                                    ])
                                    .optional(),
                                limit: zod
                                    .number()
                                    .min(1)
                                    .max(dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneLimitMax)
                                    .default(dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneLimitDefault)
                                    .describe('Maximum number of events to return.'),
                            })
                            .describe('Configuration for the recent events widget.'),
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
                        widget_type: zod.enum(['error_tracking_list']),
                        config: zod
                            .object({
                                dateRange: zod
                                    .union([
                                        zod.object({
                                            date_from: zod
                                                .union([
                                                    zod.enum([
                                                        '-1M',
                                                        '-30M',
                                                        '-1h',
                                                        '-3h',
                                                        '-24h',
                                                        '-7d',
                                                        '-14d',
                                                        '-30d',
                                                        '-90d',
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .optional(),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional(),
                                filterTestAccounts: zod.union([zod.boolean(), zod.null()]).optional(),
                                widgetFilters: zod
                                    .union([
                                        zod.record(
                                            zod.string(),
                                            zod.object({
                                                filterId: zod.string().min(1),
                                                propertyName: zod.string().min(1),
                                                optionId: zod.string().min(1),
                                                operator: zod.enum([
                                                    'exact',
                                                    'is_not',
                                                    'icontains',
                                                    'not_icontains',
                                                    'regex',
                                                    'not_regex',
                                                    'gt',
                                                    'gte',
                                                    'lt',
                                                    'lte',
                                                    'is_set',
                                                    'is_not_set',
                                                    'is_date_exact',
                                                    'is_date_before',
                                                    'is_date_after',
                                                    'between',
                                                    'not_between',
                                                    'min',
                                                    'max',
                                                    'in',
                                                    'not_in',
                                                    'is_cleaned_path_exact',
                                                    'flag_evaluates_to',
                                                    'semver_eq',
                                                    'semver_neq',
                                                    'semver_gt',
                                                    'semver_gte',
                                                    'semver_lt',
                                                    'semver_lte',
                                                    'semver_tilde',
                                                    'semver_caret',
                                                    'semver_wildcard',
                                                    'icontains_multi',
                                                    'not_icontains_multi',
                                                ]),
                                                value: zod
                                                    .union([zod.string(), zod.array(zod.string()), zod.null()])
                                                    .optional(),
                                            })
                                        ),
                                        zod.null(),
                                    ])
                                    .optional(),
                                limit: zod
                                    .number()
                                    .min(1)
                                    .max(dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneLimitMax)
                                    .default(dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneLimitDefault)
                                    .describe('Maximum number of issues to return.'),
                                orderBy: zod
                                    .enum(['last_seen', 'first_seen', 'occurrences', 'users', 'sessions'])
                                    .default(dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneOrderByDefault)
                                    .describe('Issue ranking column.'),
                                orderDirection: zod
                                    .enum(['ASC', 'DESC'])
                                    .default(
                                        dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneOrderDirectionDefault
                                    )
                                    .describe('Sort direction for orderBy.'),
                                status: zod
                                    .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed', 'all'])
                                    .default(dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneStatusDefault)
                                    .describe('Issue status filter.'),
                                assignee: zod
                                    .union([
                                        zod.object({
                                            id: zod.union([zod.string(), zod.number()]),
                                            type: zod.enum(['user', 'role']),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Filter by assignee ({type: user|role, id}). Omit for any assignee.'),
                            })
                            .describe('Configuration for the top issues widget.'),
                    }),
                    zod.object({
                        name: zod
                            .string()
                            .max(dashboardsWidgetsBatchCreateBodyWidgetsItemThreeNameMax)
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
                                dateRange: zod
                                    .union([
                                        zod.object({
                                            date_from: zod
                                                .union([
                                                    zod.enum([
                                                        '-1M',
                                                        '-30M',
                                                        '-1h',
                                                        '-3h',
                                                        '-24h',
                                                        '-7d',
                                                        '-14d',
                                                        '-30d',
                                                        '-90d',
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .optional(),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional(),
                                filterTestAccounts: zod.union([zod.boolean(), zod.null()]).optional(),
                                widgetFilters: zod
                                    .union([
                                        zod.record(
                                            zod.string(),
                                            zod.object({
                                                filterId: zod.string().min(1),
                                                propertyName: zod.string().min(1),
                                                optionId: zod.string().min(1),
                                                operator: zod.enum([
                                                    'exact',
                                                    'is_not',
                                                    'icontains',
                                                    'not_icontains',
                                                    'regex',
                                                    'not_regex',
                                                    'gt',
                                                    'gte',
                                                    'lt',
                                                    'lte',
                                                    'is_set',
                                                    'is_not_set',
                                                    'is_date_exact',
                                                    'is_date_before',
                                                    'is_date_after',
                                                    'between',
                                                    'not_between',
                                                    'min',
                                                    'max',
                                                    'in',
                                                    'not_in',
                                                    'is_cleaned_path_exact',
                                                    'flag_evaluates_to',
                                                    'semver_eq',
                                                    'semver_neq',
                                                    'semver_gt',
                                                    'semver_gte',
                                                    'semver_lt',
                                                    'semver_lte',
                                                    'semver_tilde',
                                                    'semver_caret',
                                                    'semver_wildcard',
                                                    'icontains_multi',
                                                    'not_icontains_multi',
                                                ]),
                                                value: zod
                                                    .union([zod.string(), zod.array(zod.string()), zod.null()])
                                                    .optional(),
                                            })
                                        ),
                                        zod.null(),
                                    ])
                                    .optional(),
                                limit: zod
                                    .number()
                                    .min(1)
                                    .max(dashboardsWidgetsBatchCreateBodyWidgetsItemThreeConfigOneLimitMax)
                                    .default(dashboardsWidgetsBatchCreateBodyWidgetsItemThreeConfigOneLimitDefault)
                                    .describe('Maximum number of recordings to return.'),
                                orderBy: zod
                                    .enum([
                                        'start_time',
                                        'activity_score',
                                        'recording_duration',
                                        'duration',
                                        'click_count',
                                        'console_error_count',
                                    ])
                                    .default(dashboardsWidgetsBatchCreateBodyWidgetsItemThreeConfigOneOrderByDefault)
                                    .describe('Recording ranking column.'),
                                orderDirection: zod
                                    .enum(['ASC', 'DESC'])
                                    .default(
                                        dashboardsWidgetsBatchCreateBodyWidgetsItemThreeConfigOneOrderDirectionDefault
                                    )
                                    .describe('Sort direction for orderBy.'),
                                savedFilterId: zod
                                    .union([zod.string(), zod.null()])
                                    .optional()
                                    .describe(
                                        'short_id of a saved session replay filter to use as the recordings source. When set, the saved filter owns the date range and property filters; only orderBy, orderDirection, and limit still apply.'
                                    ),
                            })
                            .describe('Configuration for the recent recordings widget.'),
                    }),
                    zod.object({
                        name: zod
                            .string()
                            .max(dashboardsWidgetsBatchCreateBodyWidgetsItemFourNameMax)
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
                        widget_type: zod.enum(['experiments_list']),
                        config: zod
                            .object({
                                limit: zod
                                    .number()
                                    .min(1)
                                    .max(dashboardsWidgetsBatchCreateBodyWidgetsItemFourConfigOneLimitMax)
                                    .default(dashboardsWidgetsBatchCreateBodyWidgetsItemFourConfigOneLimitDefault)
                                    .describe('Maximum number of experiments to return.'),
                                orderBy: zod
                                    .enum(['created_at', 'name', 'start_date'])
                                    .default(dashboardsWidgetsBatchCreateBodyWidgetsItemFourConfigOneOrderByDefault)
                                    .describe('Experiment list sort column.'),
                                orderDirection: zod
                                    .enum(['ASC', 'DESC'])
                                    .default(
                                        dashboardsWidgetsBatchCreateBodyWidgetsItemFourConfigOneOrderDirectionDefault
                                    )
                                    .describe('Sort direction for orderBy.'),
                                status: zod
                                    .enum(['draft', 'running', 'paused', 'stopped', 'all'])
                                    .default(dashboardsWidgetsBatchCreateBodyWidgetsItemFourConfigOneStatusDefault)
                                    .describe('Experiment status filter.'),
                                createdBy: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Filter by creator (user id). Omit for any creator.'),
                            })
                            .describe('Configuration for the experiments list widget.'),
                    }),
                    zod.object({
                        name: zod
                            .string()
                            .max(dashboardsWidgetsBatchCreateBodyWidgetsItemFiveNameMax)
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
                        widget_type: zod.enum(['experiment_results']),
                        config: zod
                            .object({
                                experimentId: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'Experiment to show results for. Null until the user picks one in the widget settings.'
                                    ),
                            })
                            .describe('Configuration for the experiment results widget.'),
                    }),
                ])
            )
            .min(1)
            .max(dashboardsWidgetsBatchCreateBodyWidgetsMax)
            .describe(
                'Widget tiles to add atomically. Supported widget_type values: activity_events_list, error_tracking_list, experiment_results, experiments_list, session_replay_list. Use dashboard-widget-catalog-list for per-type config_schema documentation. (1–10 per request).'
            ),
    })
    .describe('OpenAPI-only batch-add schema with widget_type-discriminated config shapes for agents.')

/**
 * List registered dashboard widget types and per-type config_schema documentation for agents.
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
