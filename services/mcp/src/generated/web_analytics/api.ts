/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 8 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Aggregated heatmap interactions for a page. For type 'click'/'rageclick'/'mousemove' each result is a point with relative x, absolute client-y, and a count. For type 'scrolldepth' the response is scroll-depth buckets instead (cumulative reach down the page).
 */
export const HeatmapsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const heatmapsListQueryAggregationDefault = `total_count`
export const heatmapsListQueryDateFromDefault = `-7d`

export const heatmapsListQueryHideZeroCoordinatesDefault = true
export const heatmapsListQueryLimitDefault = 500
export const heatmapsListQueryLimitMin = 0
export const heatmapsListQueryLimitMax = 1000000

export const heatmapsListQueryOffsetDefault = 0
export const heatmapsListQueryOffsetMin = 0
export const heatmapsListQueryOffsetMax = 1000000

export const heatmapsListQueryTypeDefault = `click`

export const HeatmapsListQueryParams = /* @__PURE__ */ zod.object({
    aggregation: zod
        .enum(['unique_visitors', 'total_count'])
        .default(heatmapsListQueryAggregationDefault)
        .describe(
            "How to aggregate counts: 'total_count' (every interaction, default) or 'unique_visitors' (distinct people).\n\n* `unique_visitors` - unique_visitors\n* `total_count` - total_count"
        ),
    cohort_ids: zod
        .string()
        .nullish()
        .describe(
            "JSON array of cohort IDs (e.g. '[123, 456]') to restrict results to people in those cohorts. Feature-flagged; ignored when the cohort filter is not enabled for the caller."
        ),
    date_from: zod
        .string()
        .min(1)
        .default(heatmapsListQueryDateFromDefault)
        .describe(
            "Start of the window. Relative (e.g. '-7d', '-30d', '-1mStart') or an absolute 'YYYY-MM-DD' date. Defaults to '-7d'. Heatmap data is retained for 90 days."
        ),
    date_to: zod
        .string()
        .min(1)
        .optional()
        .describe("End of the window, inclusive. Relative or absolute 'YYYY-MM-DD'. Defaults to today."),
    filter_test_accounts: zod
        .boolean()
        .nullish()
        .describe("When true, exclude sessions from internal/test accounts using the project's test-account filters."),
    hide_zero_coordinates: zod
        .boolean()
        .default(heatmapsListQueryHideZeroCoordinatesDefault)
        .describe('When true (default), drop interactions recorded at the (0, 0) origin, which are usually noise.'),
    limit: zod
        .number()
        .min(heatmapsListQueryLimitMin)
        .max(heatmapsListQueryLimitMax)
        .default(heatmapsListQueryLimitDefault)
        .describe(
            "Maximum number of coordinate points to return, ordered hottest-first by count. Defaults to 500. Pass 0 to fetch the full set (every coordinate) needed to render a complete heatmap overlay. Ignored for the 'scrolldepth' type, which always returns every bucket."
        ),
    offset: zod
        .number()
        .min(heatmapsListQueryOffsetMin)
        .max(heatmapsListQueryOffsetMax)
        .default(heatmapsListQueryOffsetDefault)
        .describe(
            "Number of hottest-first points to skip, for paging through cooler coordinates. Ignored for the 'scrolldepth' type."
        ),
    type: zod
        .string()
        .min(1)
        .default(heatmapsListQueryTypeDefault)
        .describe(
            "The interaction type to return. One of: 'click' (default), 'rageclick', 'mousemove', or 'scrolldepth'. Scrolldepth returns scroll buckets instead of x/y coordinates."
        ),
    url_exact: zod
        .string()
        .min(1)
        .optional()
        .describe('Match a single page by exact URL (trailing slash is ignored). Mutually exclusive with url_pattern.'),
    url_pattern: zod
        .string()
        .min(1)
        .optional()
        .describe(
            'Match pages by regex against the full current_url (anchored automatically). Use this to aggregate across query strings or path segments. Mutually exclusive with url_exact.'
        ),
    viewport_width_max: zod
        .number()
        .optional()
        .describe('Only include interactions captured at a viewport at most this wide, in CSS pixels.'),
    viewport_width_min: zod
        .number()
        .optional()
        .describe(
            'Only include interactions captured at a viewport at least this wide, in CSS pixels. Use with viewport_width_max to isolate a device class (e.g. 360-768 for mobile).'
        ),
})

/**
 * Drill into the individual session interactions behind one or more heatmap coordinates. Pass the 'points' you want to inspect (from the heatmaps list response) to get the underlying per-session events, so you can jump to the session recordings that produced a hotspot.
 */
export const HeatmapsEventsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const heatmapsEventsRetrieveQueryAggregationDefault = `total_count`
export const heatmapsEventsRetrieveQueryDateFromDefault = `-7d`

export const heatmapsEventsRetrieveQueryHideZeroCoordinatesDefault = true
export const heatmapsEventsRetrieveQueryLimitDefault = 50
export const heatmapsEventsRetrieveQueryLimitMax = 100

export const heatmapsEventsRetrieveQueryOffsetDefault = 0
export const heatmapsEventsRetrieveQueryOffsetMin = 0

export const heatmapsEventsRetrieveQueryTypeDefault = `click`

export const HeatmapsEventsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    aggregation: zod
        .enum(['unique_visitors', 'total_count'])
        .default(heatmapsEventsRetrieveQueryAggregationDefault)
        .describe(
            "How to aggregate counts: 'total_count' (every interaction, default) or 'unique_visitors' (distinct people).\n\n* `unique_visitors` - unique_visitors\n* `total_count` - total_count"
        ),
    cohort_ids: zod
        .string()
        .nullish()
        .describe(
            "JSON array of cohort IDs (e.g. '[123, 456]') to restrict results to people in those cohorts. Feature-flagged; ignored when the cohort filter is not enabled for the caller."
        ),
    date_from: zod
        .string()
        .min(1)
        .default(heatmapsEventsRetrieveQueryDateFromDefault)
        .describe(
            "Start of the window. Relative (e.g. '-7d', '-30d', '-1mStart') or an absolute 'YYYY-MM-DD' date. Defaults to '-7d'. Heatmap data is retained for 90 days."
        ),
    date_to: zod
        .string()
        .min(1)
        .optional()
        .describe("End of the window, inclusive. Relative or absolute 'YYYY-MM-DD'. Defaults to today."),
    filter_test_accounts: zod
        .boolean()
        .nullish()
        .describe("When true, exclude sessions from internal/test accounts using the project's test-account filters."),
    hide_zero_coordinates: zod
        .boolean()
        .default(heatmapsEventsRetrieveQueryHideZeroCoordinatesDefault)
        .describe('When true (default), drop interactions recorded at the (0, 0) origin, which are usually noise.'),
    limit: zod
        .number()
        .min(1)
        .max(heatmapsEventsRetrieveQueryLimitMax)
        .default(heatmapsEventsRetrieveQueryLimitDefault)
        .describe('Maximum interactions to return (1-100).'),
    offset: zod
        .number()
        .min(heatmapsEventsRetrieveQueryOffsetMin)
        .default(heatmapsEventsRetrieveQueryOffsetDefault)
        .describe('Number of interactions to skip, for pagination.'),
    points: zod
        .string()
        .min(1)
        .describe(
            "JSON array of the heatmap coordinates to drill into, e.g. '[{\"x\": 0.5, \"y\": 100}]'. Each point needs 'x' (relative x, 0..1) and 'y' (absolute client-y pixels) matching values returned by the heatmaps list endpoint; an optional 'target_fixed' boolean matches fixed-position elements. Returns the individual session interactions behind those spots."
        ),
    type: zod
        .string()
        .min(1)
        .default(heatmapsEventsRetrieveQueryTypeDefault)
        .describe(
            "The interaction type to return. One of: 'click' (default), 'rageclick', 'mousemove', or 'scrolldepth'. Scrolldepth returns scroll buckets instead of x/y coordinates."
        ),
    url_exact: zod
        .string()
        .min(1)
        .optional()
        .describe('Match a single page by exact URL (trailing slash is ignored). Mutually exclusive with url_pattern.'),
    url_pattern: zod
        .string()
        .min(1)
        .optional()
        .describe(
            'Match pages by regex against the full current_url (anchored automatically). Use this to aggregate across query strings or path segments. Mutually exclusive with url_exact.'
        ),
    viewport_width_max: zod
        .number()
        .optional()
        .describe('Only include interactions captured at a viewport at most this wide, in CSS pixels.'),
    viewport_width_min: zod
        .number()
        .optional()
        .describe(
            'Only include interactions captured at a viewport at least this wide, in CSS pixels. Use with viewport_width_max to isolate a device class (e.g. 360-768 for mobile).'
        ),
})

/**
 * List saved heatmaps for the project. A saved heatmap pins a page URL and a set of viewport widths, and (for type 'screenshot') renders the page so heatmap data can be overlaid on it.
 */
export const SavedListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const savedListQueryLimitDefault = 100
export const savedListQueryOffsetDefault = 0

export const SavedListQueryParams = /* @__PURE__ */ zod.object({
    created_by: zod.number().optional().describe("Filter by the creating user's ID."),
    limit: zod.number().default(savedListQueryLimitDefault).describe('Maximum saved heatmaps to return.'),
    offset: zod.number().default(savedListQueryOffsetDefault).describe('Number to skip, for pagination.'),
    order: zod.string().min(1).optional().describe("Field to order by, e.g. '-updated_at' (default) or 'created_at'."),
    search: zod.string().min(1).optional().describe('Case-insensitive substring match on URL or name.'),
    status: zod
        .string()
        .min(1)
        .optional()
        .describe("Filter by generation status: 'processing', 'completed', or 'failed'."),
    type: zod.string().min(1).optional().describe("Filter by render mode: 'screenshot', 'iframe', or 'recording'."),
})

/**
 * Create a saved heatmap for a page URL. For type 'screenshot' (the default) this enqueues a headless render of the page at each target width; poll the saved heatmap or its content endpoint until status is 'completed'. Provide 'widths' to control which viewport widths are rendered.
 */
export const SavedCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const savedCreateBodyNameMax = 400

export const savedCreateBodyUrlMax = 2000

export const savedCreateBodyDataUrlMax = 2000

export const savedCreateBodyWidthsItemMin = 100
export const savedCreateBodyWidthsItemMax = 3000

export const savedCreateBodyWidthsMax = 16

export const savedCreateBodyTypeDefault = `screenshot`

export const SavedCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(savedCreateBodyNameMax).nullish().describe('Human-readable label for the saved heatmap.'),
    url: zod
        .url()
        .max(savedCreateBodyUrlMax)
        .describe('Exact page URL to render and overlay heatmap data on. Wildcards are not allowed.'),
    data_url: zod
        .url()
        .max(savedCreateBodyDataUrlMax)
        .nullish()
        .describe("URL whose heatmap data is overlaid on the screenshot. Defaults to 'url' when omitted."),
    widths: zod
        .array(zod.number().min(savedCreateBodyWidthsItemMin).max(savedCreateBodyWidthsItemMax))
        .max(savedCreateBodyWidthsMax)
        .optional()
        .describe(
            'Viewport widths (px, 100-3000) to render the heatmap screenshot at — one render per width. Defaults to [320, 375, 425, 768, 1024, 1440, 1920] when omitted. At most 16 widths.'
        ),
    type: zod
        .enum(['screenshot', 'iframe', 'recording'])
        .describe('* `screenshot` - Screenshot\n* `iframe` - Iframe\n* `recording` - Recording')
        .default(savedCreateBodyTypeDefault)
        .describe(
            "Render mode: 'screenshot' (renders the page headlessly, default), 'iframe', or 'recording'. Only 'screenshot' generates image bytes.\n\n* `screenshot` - Screenshot\n* `iframe` - Iframe\n* `recording` - Recording"
        ),
    block_consent_modals: zod
        .boolean()
        .optional()
        .describe(
            "When true, ask the headless browser to dismiss cookie/consent banners before capturing the screenshot. Off by default: the blocker can stall the render on some sites and time out. Only applies to 'screenshot' heatmaps."
        ),
})

/**
 * Get a single saved heatmap by its short_id, including per-width render status.
 */
export const SavedRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    short_id: zod.string(),
})

/**
 * Update a saved heatmap (e.g. rename, change widths, or soft-delete via 'deleted'). Changing the URL of a 'screenshot' heatmap triggers a re-render.
 */
export const SavedPartialUpdateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    short_id: zod.string(),
})

export const savedPartialUpdateBodyNameMax = 400

export const savedPartialUpdateBodyUrlMax = 2000

export const savedPartialUpdateBodyDataUrlMax = 2000

export const savedPartialUpdateBodyWidthsItemMin = 100
export const savedPartialUpdateBodyWidthsItemMax = 3000

export const savedPartialUpdateBodyWidthsMax = 16

export const SavedPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(savedPartialUpdateBodyNameMax)
        .nullish()
        .describe('Human-readable label for the saved heatmap.'),
    url: zod
        .url()
        .max(savedPartialUpdateBodyUrlMax)
        .optional()
        .describe('Exact page URL to render and overlay heatmap data on. Wildcards are not allowed.'),
    data_url: zod
        .url()
        .max(savedPartialUpdateBodyDataUrlMax)
        .nullish()
        .describe("URL whose heatmap data is overlaid on the screenshot. Defaults to 'url' when omitted."),
    widths: zod
        .array(zod.number().min(savedPartialUpdateBodyWidthsItemMin).max(savedPartialUpdateBodyWidthsItemMax))
        .max(savedPartialUpdateBodyWidthsMax)
        .optional()
        .describe(
            'Viewport widths (px, 100-3000) to render the heatmap screenshot at — one render per width. Defaults to [320, 375, 425, 768, 1024, 1440, 1920] when omitted. At most 16 widths.'
        ),
    type: zod
        .enum(['screenshot', 'iframe', 'recording'])
        .describe('* `screenshot` - Screenshot\n* `iframe` - Iframe\n* `recording` - Recording')
        .optional()
        .describe(
            "Render mode: 'screenshot' (renders the page headlessly, default), 'iframe', or 'recording'. Only 'screenshot' generates image bytes.\n\n* `screenshot` - Screenshot\n* `iframe` - Iframe\n* `recording` - Recording"
        ),
    deleted: zod.boolean().optional().describe('Set true to soft-delete the saved heatmap.'),
    block_consent_modals: zod
        .boolean()
        .optional()
        .describe(
            "When true, ask the headless browser to dismiss cookie/consent banners before capturing the screenshot. Off by default: the blocker can stall the render on some sites and time out. Only applies to 'screenshot' heatmaps."
        ),
})

/**
 * Re-run screenshot generation for a saved heatmap of type 'screenshot'. Clears existing renders and re-renders at every target width; status returns to 'processing'.
 */
export const SavedRegenerateCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    short_id: zod.string(),
})

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
