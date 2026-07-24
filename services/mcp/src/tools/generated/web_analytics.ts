// AUTO-GENERATED from products/web_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    HeatmapsEventsRetrieveQueryParams,
    HeatmapsListQueryParams,
    SavedCreateBody,
    SavedListQueryParams,
    SavedPartialUpdateBody,
    SavedPartialUpdateParams,
    SavedRegenerateCreateParams,
    SavedRetrieveParams,
    WebAnalyticsWeeklyDigestQueryParams,
} from '@/generated/web_analytics/api'
import { createQueryWrapper } from '@/tools/query-wrapper-factory'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const HeatmapsEventsSchema = HeatmapsEventsRetrieveQueryParams

const heatmapsEvents = (): ToolBase<typeof HeatmapsEventsSchema, Schemas.HeatmapEventsResponse> => ({
    name: 'heatmaps-events',
    schema: HeatmapsEventsSchema,
    handler: async (context: Context, params: z.infer<typeof HeatmapsEventsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HeatmapEventsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/heatmaps/events/`,
            query: {
                aggregation: params.aggregation,
                cohort_ids: params.cohort_ids,
                date_from: params.date_from,
                date_to: params.date_to,
                filter_test_accounts: params.filter_test_accounts,
                hide_zero_coordinates: params.hide_zero_coordinates,
                limit: params.limit,
                offset: params.offset,
                points: params.points,
                type: params.type,
                url_exact: params.url_exact,
                url_pattern: params.url_pattern,
                viewport_width_max: params.viewport_width_max,
                viewport_width_min: params.viewport_width_min,
            },
        })
        return result
    },
})

const HeatmapsListSchema = HeatmapsListQueryParams

const heatmapsList = (): ToolBase<typeof HeatmapsListSchema, WithPostHogUrl<Schemas.HeatmapsResponse[]>> => ({
    name: 'heatmaps-list',
    schema: HeatmapsListSchema,
    handler: async (context: Context, params: z.infer<typeof HeatmapsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HeatmapsResponse[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/heatmaps/`,
            query: {
                aggregation: params.aggregation,
                cohort_ids: params.cohort_ids,
                date_from: params.date_from,
                date_to: params.date_to,
                filter_test_accounts: params.filter_test_accounts,
                hide_zero_coordinates: params.hide_zero_coordinates,
                limit: params.limit,
                offset: params.offset,
                type: params.type,
                url_exact: params.url_exact,
                url_pattern: params.url_pattern,
                viewport_width_max: params.viewport_width_max,
                viewport_width_min: params.viewport_width_min,
            },
        })
        return await withPostHogUrl(context, result, '/web')
    },
})

const HeatmapsSavedCreateSchema = SavedCreateBody

const heatmapsSavedCreate = (): ToolBase<typeof HeatmapsSavedCreateSchema, Schemas.HeatmapScreenshotResponse> => ({
    name: 'heatmaps-saved-create',
    schema: HeatmapsSavedCreateSchema,
    handler: async (context: Context, params: z.infer<typeof HeatmapsSavedCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.url !== undefined) {
            body['url'] = params.url
        }
        if (params.data_url !== undefined) {
            body['data_url'] = params.data_url
        }
        if (params.widths !== undefined) {
            body['widths'] = params.widths
        }
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        if (params.block_consent_modals !== undefined) {
            body['block_consent_modals'] = params.block_consent_modals
        }
        const result = await context.api.request<Schemas.HeatmapScreenshotResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/saved/`,
            body,
        })
        return result
    },
})

const HeatmapsSavedGetSchema = SavedRetrieveParams.omit({ project_id: true })

const heatmapsSavedGet = (): ToolBase<typeof HeatmapsSavedGetSchema, Schemas.HeatmapScreenshotResponse> => ({
    name: 'heatmaps-saved-get',
    schema: HeatmapsSavedGetSchema,
    handler: async (context: Context, params: z.infer<typeof HeatmapsSavedGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HeatmapScreenshotResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/saved/${encodeURIComponent(String(params.short_id))}/`,
        })
        return result
    },
})

const HeatmapsSavedListSchema = SavedListQueryParams

const heatmapsSavedList = (): ToolBase<
    typeof HeatmapsSavedListSchema,
    WithPostHogUrl<Schemas.SavedHeatmapListResponse[]>
> => ({
    name: 'heatmaps-saved-list',
    schema: HeatmapsSavedListSchema,
    handler: async (context: Context, params: z.infer<typeof HeatmapsSavedListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SavedHeatmapListResponse[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/saved/`,
            query: {
                created_by: params.created_by,
                limit: params.limit,
                offset: params.offset,
                order: params.order,
                search: params.search,
                status: params.status,
                type: params.type,
            },
        })
        return await withPostHogUrl(context, result, '/web')
    },
})

const HeatmapsSavedRegenerateSchema = SavedRegenerateCreateParams.omit({ project_id: true })

const heatmapsSavedRegenerate = (): ToolBase<
    typeof HeatmapsSavedRegenerateSchema,
    Schemas.HeatmapScreenshotResponse
> => ({
    name: 'heatmaps-saved-regenerate',
    schema: HeatmapsSavedRegenerateSchema,
    handler: async (context: Context, params: z.infer<typeof HeatmapsSavedRegenerateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HeatmapScreenshotResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/saved/${encodeURIComponent(String(params.short_id))}/regenerate/`,
        })
        return result
    },
})

const HeatmapsSavedUpdateSchema = SavedPartialUpdateParams.omit({ project_id: true }).extend(
    SavedPartialUpdateBody.shape
)

const heatmapsSavedUpdate = (): ToolBase<typeof HeatmapsSavedUpdateSchema, Schemas.HeatmapScreenshotResponse> => ({
    name: 'heatmaps-saved-update',
    schema: HeatmapsSavedUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof HeatmapsSavedUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.url !== undefined) {
            body['url'] = params.url
        }
        if (params.data_url !== undefined) {
            body['data_url'] = params.data_url
        }
        if (params.widths !== undefined) {
            body['widths'] = params.widths
        }
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        if (params.block_consent_modals !== undefined) {
            body['block_consent_modals'] = params.block_consent_modals
        }
        const result = await context.api.request<Schemas.HeatmapScreenshotResponse>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/saved/${encodeURIComponent(String(params.short_id))}/`,
            body,
        })
        return result
    },
})

const WebAnalyticsWeeklyDigestSchema = WebAnalyticsWeeklyDigestQueryParams

const webAnalyticsWeeklyDigest = (): ToolBase<typeof WebAnalyticsWeeklyDigestSchema, Schemas.WeeklyDigestResponse> => ({
    name: 'web-analytics-weekly-digest',
    schema: WebAnalyticsWeeklyDigestSchema,
    handler: async (context: Context, params: z.infer<typeof WebAnalyticsWeeklyDigestSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.WeeklyDigestResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/web_analytics/weekly_digest/`,
            query: {
                compare: params.compare,
                days: params.days,
            },
        })
        return result
    },
})

// --- Query wrapper schemas from schema.json ---

const CompareFilter = z.object({
    compare: z.coerce
        .boolean()
        .describe('Whether to compare the current date range to a previous date range.')
        .default(false)
        .optional(),
    compare_to: z
        .string()
        .describe(
            'The date range to compare to. The value is a relative date. Examples of relative dates are: `-1y` for 1 year ago, `-14m` for 14 months ago, `-100w` for 100 weeks ago, `-14d` for 14 days ago, `-30h` for 30 hours ago.'
        )
        .optional(),
})

const integer = z.coerce.number().int()

const ActionConversionGoal = z.object({
    actionId: integer,
})

const CustomEventConversionGoal = z.object({
    customEventName: z.string(),
})

const WebAnalyticsConversionGoal = z.union([ActionConversionGoal, CustomEventConversionGoal])

const AssistantDateRange = z.object({
    date_from: z.string().describe('ISO8601 date string.'),
    date_to: z.string().nullable().describe('ISO8601 date string.').optional(),
})

const AssistantDurationRange = z.object({
    date_from: z
        .string()
        .describe(
            "Duration in the past. Supported units are: `h` (hour), `d` (day), `w` (week), `m` (month), `y` (year), `all` (all time). Use the `Start` suffix to define the exact left date boundary. Examples: `-1d` last day from now, `-180d` last 180 days from now, `mStart` this month start, `-1dStart` yesterday's start."
        ),
})

const AssistantDateRangeFilter = z.union([AssistantDateRange, AssistantDurationRange])

const PropertyOperator = z.enum([
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
])

const PropertyFilterBaseValue = z.union([z.string(), z.coerce.number(), z.coerce.boolean()])

const PropertyFilterValue = z.union([PropertyFilterBaseValue, z.array(PropertyFilterBaseValue), z.null()])

const EventPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator.default('exact'),
    type: z.literal('event').describe('Event properties').default('event'),
    value: PropertyFilterValue.optional(),
})

const PersonPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('person').describe('Person properties').default('person'),
    value: PropertyFilterValue.optional(),
})

const SessionPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('session').default('session'),
    value: PropertyFilterValue.optional(),
})

const CohortPropertyFilter = z.object({
    cohort_name: z.string().optional(),
    key: z.literal('id').default('id'),
    label: z.string().optional(),
    operator: PropertyOperator.default('in'),
    type: z.literal('cohort').default('cohort'),
    value: z.coerce.number().int(),
})

const WebAnalyticsPropertyFilter = z.union([
    EventPropertyFilter,
    PersonPropertyFilter,
    SessionPropertyFilter,
    CohortPropertyFilter,
])

const WebAnalyticsPropertyFilters = z.array(WebAnalyticsPropertyFilter)

const AssistantWebOverviewQuery = z.object({
    compareFilter: CompareFilter.describe(
        'Compare the current period to a prior period. Disabled by default. Enabling roughly doubles query cost — leave it off unless the user explicitly asks for a period-over-period comparison.'
    ).optional(),
    conversionGoal: z
        .union([WebAnalyticsConversionGoal, z.null()])
        .describe(
            'Conversion goal — pass an `actionId` (must belong to the current project) or a `customEventName`. Adds conversion columns to the response. Disables the pre-aggregated fast path — only set when the user explicitly asks about a conversion.'
        )
        .optional(),
    dateRange: AssistantDateRangeFilter.describe(
        'Date range for the query. Defaults to the last 7 days when omitted. Keep ranges short — the backend has no upper bound and large windows on the slow path (e.g. with `conversionGoal` or `includeAvgTimeOnPage`) can be expensive.'
    ).optional(),
    doPathCleaning: z.coerce
        .boolean()
        .describe("Apply the team's path-cleaning rules to URL-style breakdowns.")
        .default(false)
        .optional(),
    filterTestAccounts: z.coerce
        .boolean()
        .describe("Exclude internal and test users by applying the team's test-account filter.")
        .default(false)
        .optional(),
    kind: z.literal('WebOverviewQuery').default('WebOverviewQuery'),
    properties: WebAnalyticsPropertyFilters.describe(
        'Property filters applied to the query. Accepts event, person, session, or cohort filters.'
    )
        .default([])
        .optional(),
})

const WebStatsBreakdown = z.enum([
    'Page',
    'InitialPage',
    'ExitPage',
    'ExitClick',
    'PreviousPage',
    'ScreenName',
    'InitialChannelType',
    'InitialReferringDomain',
    'InitialReferringURL',
    'InitialUTMSource',
    'InitialUTMCampaign',
    'InitialUTMMedium',
    'InitialUTMTerm',
    'InitialUTMContent',
    'InitialUTMSourceMediumCampaign',
    'Browser',
    'OS',
    'Viewport',
    'DeviceType',
    'Country',
    'Region',
    'City',
    'Timezone',
    'Language',
    'FrustrationMetrics',
])

const positive_integer = z.coerce.number().int().min(1)

const non_negative_integer = z.coerce.number().int().min(0)

const AssistantWebStatsTableQuery = z.object({
    breakdownBy: WebStatsBreakdown.describe(
        'Required. Property to break down the table by. The full enum covers path-style (`Page`, `InitialPage`, `ExitPage`, `PreviousPage`), marketing/source (UTM source/medium/campaign/term/content, channel, referring domain), audience/device (browser, OS, device type, viewport), and geography (country, region, city, timezone, language). Path-style breakdowns pair naturally with `includeBounceRate` / `includeAvgTimeOnPage`.'
    ),
    compareFilter: CompareFilter.describe(
        'Compare the current period to a prior period. Disabled by default. Enabling roughly doubles query cost — leave it off unless the user explicitly asks for a period-over-period comparison.'
    ).optional(),
    conversionGoal: z
        .union([WebAnalyticsConversionGoal, z.null()])
        .describe(
            'Conversion goal — pass an `actionId` (must belong to the current project) or a `customEventName`. Adds conversion columns to the response. Disables the pre-aggregated fast path — only set when the user explicitly asks about a conversion.'
        )
        .optional(),
    dateRange: AssistantDateRangeFilter.describe(
        'Date range for the query. Defaults to the last 7 days when omitted. Keep ranges short — the backend has no upper bound and large windows on the slow path (e.g. with `conversionGoal` or `includeAvgTimeOnPage`) can be expensive.'
    ).optional(),
    doPathCleaning: z.coerce
        .boolean()
        .describe("Apply the team's path-cleaning rules to URL-style breakdowns.")
        .default(false)
        .optional(),
    filterTestAccounts: z.coerce
        .boolean()
        .describe("Exclude internal and test users by applying the team's test-account filter.")
        .default(false)
        .optional(),
    includeAvgTimeOnPage: z.coerce
        .boolean()
        .describe(
            'Add an average-time-on-page column. Implies a Page-style breakdown. Disables the pre-aggregated fast path.'
        )
        .default(false)
        .optional(),
    includeBounceRate: z.coerce
        .boolean()
        .describe('Add a bounce-rate column. Most useful with a path-style breakdown.')
        .default(false)
        .optional(),
    includeHost: z.coerce
        .boolean()
        .describe(
            'When using a path-style breakdown (`Page`, `InitialPage`, `ExitPage`, `PreviousPage`), concatenate host + pathname so the same path on different hosts is counted separately.'
        )
        .default(false)
        .optional(),
    kind: z.literal('WebStatsTableQuery').default('WebStatsTableQuery'),
    limit: positive_integer
        .max(200)
        .describe(
            'Maximum rows to return. Prefer 10–25 unless the user explicitly asks for more. Hard ceiling enforced at the wrapper.'
        )
        .optional(),
    offset: non_negative_integer.describe('Pagination offset.').optional(),
    properties: WebAnalyticsPropertyFilters.describe(
        'Property filters applied to the query. Accepts event, person, session, or cohort filters.'
    )
        .default([])
        .optional(),
})

const WebVitalsMetric = z.enum(['INP', 'LCP', 'CLS', 'FCP'])

const WebVitalsPercentile = z.enum(['p75', 'p90', 'p99'])

const AssistantWebVitalsPathBreakdownQuery = z.object({
    dateRange: AssistantDateRangeFilter.describe(
        'Date range for the query. Defaults to the last 7 days when omitted — a good window for a stable percentile.'
    ).optional(),
    doPathCleaning: z.coerce
        .boolean()
        .describe("Apply the team's path-cleaning rules to the returned paths.")
        .default(false)
        .optional(),
    filterTestAccounts: z.coerce
        .boolean()
        .describe("Exclude internal and test users by applying the team's test-account filter.")
        .default(false)
        .optional(),
    kind: z.literal('WebVitalsPathBreakdownQuery').default('WebVitalsPathBreakdownQuery'),
    metric: WebVitalsMetric.describe(
        'Required. Which Core Web Vital to break down by: `LCP` (load, ms), `INP` (interactivity, ms), `CLS` (layout stability, unitless score), or `FCP` (first paint, ms).'
    ),
    percentile: WebVitalsPercentile.describe(
        "Required. Percentile to aggregate each page's samples at. Use `p75` unless the user asks otherwise — the Google bands are defined at p75."
    ),
    properties: z
        .array(z.union([EventPropertyFilter, PersonPropertyFilter]))
        .describe(
            'Property filters applied to the query. Accepts event and person filters only (the query runner ignores session and cohort filters) — e.g. an event filter on `$host` to scope to one domain, or on `$device_type` to isolate mobile.'
        )
        .default([])
        .optional(),
    thresholds: z
        .array(z.coerce.number())
        .min(2)
        .max(2)
        .describe(
            'Required. `[good, poor]` band boundaries for the chosen metric. Values below `good` are good, above `poor` are poor, in between need improvement. Use the standard Google thresholds unless the user supplies their own: LCP `[2500, 4000]`, INP `[200, 500]`, CLS `[0.1, 0.25]`, FCP `[1800, 3000]`.'
        ),
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'heatmaps-events': heatmapsEvents,
    'heatmaps-list': heatmapsList,
    'heatmaps-saved-create': heatmapsSavedCreate,
    'heatmaps-saved-get': heatmapsSavedGet,
    'heatmaps-saved-list': heatmapsSavedList,
    'heatmaps-saved-regenerate': heatmapsSavedRegenerate,
    'heatmaps-saved-update': heatmapsSavedUpdate,
    'web-analytics-weekly-digest': webAnalyticsWeeklyDigest,
    'query-web-overview': createQueryWrapper({
        name: 'query-web-overview',
        schema: AssistantWebOverviewQuery,
        kind: 'WebOverviewQuery',
        uiResourceUri: 'ui://posthog/query-results.html',
    }),
    'query-web-stats': createQueryWrapper({
        name: 'query-web-stats',
        schema: AssistantWebStatsTableQuery,
        kind: 'WebStatsTableQuery',
        uiResourceUri: 'ui://posthog/query-results.html',
    }),
    'query-web-vitals': createQueryWrapper({
        name: 'query-web-vitals',
        schema: AssistantWebVitalsPathBreakdownQuery,
        kind: 'WebVitalsPathBreakdownQuery',
        uiResourceUri: 'ui://posthog/query-results.html',
    }),
}
