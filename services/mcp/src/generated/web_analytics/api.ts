/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 1 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Summarizes a project's web analytics over a lookback window (default 7 days): unique visitors, pageviews, sessions, bounce rate, and average session duration with period-over-period comparisons, plus the top 5 pages, top 5 traffic sources, and goal conversions.
 * @summary Summarize web analytics
 */
export const WebAnalyticsWeeklyDigestParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const webAnalyticsWeeklyDigestQueryCompareDefault = true
export const webAnalyticsWeeklyDigestQueryDaysDefault = 7

export const WebAnalyticsWeeklyDigestQueryParams = /* @__PURE__ */ zod.object({
    compare: zod
        .boolean()
        .default(webAnalyticsWeeklyDigestQueryCompareDefault)
        .describe(
            'When true (default), include period-over-period change for each metric comparing against the prior equal-length period. Set to false to skip the comparison query (faster).'
        ),
    days: zod
        .number()
        .default(webAnalyticsWeeklyDigestQueryDaysDefault)
        .describe('Lookback window in days (1–90). Defaults to 7.'),
})
