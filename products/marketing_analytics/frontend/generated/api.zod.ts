/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Apply one or more setup operations from the setup plan, atomically. Either every operation lands or none does — a partially-applied batch has no well-defined undo. Returns `undo_ops`, computed from the pre-change state, which can be POSTed back to reverse the batch. Only send `apply` payloads returned by setup_plan.
 * @summary Apply setup operations
 */
export const marketingAnalyticsApplySetupOpsCreateBodySourceDefault = `setup_tab`

export const MarketingAnalyticsApplySetupOpsCreateBody = /* @__PURE__ */ zod.object({
    ops: zod
        .array(zod.unknown())
        .describe(
            'Operations to apply, in order. Send `apply` payloads returned verbatim by setup_plan — never hand-craft one. Navigate-only ops (open_oauth, open_source_wizard, open_settings, fix_platform_urls) are rejected: they describe something a browser or a human does.'
        ),
    source: zod
        .enum(['setup_tab', 'apply_all_safe', 'mcp'])
        .describe('\* `setup_tab` - setup_tab\n\* `apply_all_safe` - apply_all_safe\n\* `mcp` - mcp')
        .default(marketingAnalyticsApplySetupOpsCreateBodySourceDefault)
        .describe(
            'Where the request came from, recorded in the activity log\n\n\* `setup_tab` - setup_tab\n\* `apply_all_safe` - apply_all_safe\n\* `mcp` - mcp'
        ),
})

/**
 * Change one conversion goal in place. Fields you send are merged into the stored goal, the rest are kept, and the goal keeps its position in the list. Sending a different `kind` replaces the goal instead, since the shapes don't share their fields.
 * @summary Update conversion goal
 */
export const MarketingAnalyticsConversionGoalsUpdatePartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Add one conversion goal to the project. The server assigns conversion_goal_id and appends the goal to the end of the list, leaving existing goals untouched.
 * @summary Create conversion goal
 */
export const MarketingAnalyticsConversionGoalsCreateCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const MarketingAnalyticsConversionRecordingsListBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const marketingAnalyticsSearchRecommendationsCreateBodyQueryOneCompareFilterOneCompareDefault = false
export const marketingAnalyticsSearchRecommendationsCreateBodyQueryOneDateRangeOneExcludeIncompletePeriodsDefault = false
export const marketingAnalyticsSearchRecommendationsCreateBodyQueryOneDateRangeOneExplicitDateDefault = false

export const MarketingAnalyticsSearchRecommendationsCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            sources: zod
                .array(
                    zod.object({
                        keywordTable: zod.union([zod.string(), zod.null()]).optional(),
                        placementTable: zod.union([zod.string(), zod.null()]).optional(),
                        queryPageTable: zod.union([zod.boolean(), zod.null()]).optional(),
                        sourceType: zod.enum(['GoogleAds', 'BingAds', 'GoogleSearchConsole']),
                        statsTable: zod.string(),
                    })
                )
                .describe('Connected search source tables from the search report.'),
            breakdown: zod.union([zod.enum(['keyword', 'page']), zod.null()]).optional(),
            compareFilter: zod
                .union([
                    zod.object({
                        compare: zod
                            .union([zod.boolean(), zod.null()])
                            .default(
                                marketingAnalyticsSearchRecommendationsCreateBodyQueryOneCompareFilterOneCompareDefault
                            )
                            .describe('Whether to compare the current date range to a previous date range.'),
                        compare_to: zod
                            .union([zod.string(), zod.null()])
                            .optional()
                            .describe(
                                'The date range to compare to. The value is a relative date. Examples of relative dates are: `-1y` for 1 year ago, `-14m` for 14 months ago, `-100w` for 100 weeks ago, `-14d` for 14 days ago, `-30h` for 30 hours ago.'
                            ),
                    }),
                    zod.null(),
                ])
                .optional(),
            dateRange: zod
                .union([
                    zod.object({
                        date_from: zod
                            .union([zod.string(), zod.null()])
                            .optional()
                            .describe(
                                'Start of the date range. Accepts ISO 8601 timestamps (e.g., 2024-01-15T00:00:00Z) or relative formats: -7d (7 days ago), -2w (2 weeks ago), -1m (1 month ago),\n-1h (1 hour ago), -1mStart (start of last month), -1yStart (start of last year).'
                            ),
                        date_to: zod
                            .union([zod.string(), zod.null()])
                            .optional()
                            .describe(
                                'End of the date range. Same format as date_from. Omit or null for \"now\". A calendar day without a time (2024-01-15) is inclusive: it rounds to the last moment of that day in the project timezone, unless explicitDate is set.'
                            ),
                        daysOfWeek: zod
                            .union([
                                zod.array(
                                    zod.union([
                                        zod.literal(1),
                                        zod.literal(2),
                                        zod.literal(3),
                                        zod.literal(4),
                                        zod.literal(5),
                                        zod.literal(6),
                                        zod.literal(7),
                                    ])
                                ),
                                zod.null(),
                            ])
                            .optional()
                            .describe(
                                'Restrict the query to events occurring on these ISO days of week (1=Monday to 7=Sunday), evaluated in the project timezone. Omit or empty for all days. Only applied by insight queries.'
                            ),
                        excludeIncompletePeriods: zod
                            .union([zod.boolean(), zod.null()])
                            .default(
                                marketingAnalyticsSearchRecommendationsCreateBodyQueryOneDateRangeOneExcludeIncompletePeriodsDefault
                            )
                            .describe(
                                'Exclude the current, still-collecting period by clipping date_to to the end of the last complete interval (evaluated in the project timezone). No-op when the range contains no complete interval. Only applied by insight queries.'
                            ),
                        explicitDate: zod
                            .union([zod.boolean(), zod.null()])
                            .default(
                                marketingAnalyticsSearchRecommendationsCreateBodyQueryOneDateRangeOneExplicitDateDefault
                            )
                            .describe(
                                'Whether the date_from and date_to should be used verbatim. Disables rounding to the start and end of period.'
                            ),
                    }),
                    zod.null(),
                ])
                .optional(),
            keyword: zod.union([zod.string(), zod.null()]).optional(),
            page: zod.union([zod.string(), zod.null()]).optional(),
            search: zod.union([zod.string(), zod.null()]).optional(),
            normalizePageUrls: zod.union([zod.boolean(), zod.null()]).optional(),
        })
        .describe('Search report filters and connected source tables to analyze.'),
    goal_id: zod
        .string()
        .nullish()
        .describe(
            'PostHog conversion goal ID. Omit to use ad platform conversions. Goals are never combined or substituted.'
        ),
})
