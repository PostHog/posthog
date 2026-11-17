import type { WebBreakdown, WebPropertyFilter, WebTrendMetric } from '@/model/views'

import type { QueryStatusFieldsApi, ResolvedDateRangeApi } from './insights'
import { type QueryRefresh, runQuery } from './query'

// Shapes follow `WebOverviewQuery`, `WebStatsTableQuery`, `WebExternalClicksTableQuery`, `TrendsQuery`, `RetentionQuery`
// and their cached responses in `posthog/schema.py`. The query builders port the web's tiles in
// `frontend/src/scenes/web-analytics/webAnalyticsLogic.tsx`, so a phone read with the web's range can share its cache.

export interface WebOverviewItemApi {
    /** `visitors`, `views`, `sessions`, `session duration`, `bounce rate`, and revenue or conversion keys. */
    key: string
    /** `unit`, `duration_s`, `percentage` or `currency`. */
    kind: string
    value?: number | null
    previous?: number | null
    changeFromPreviousPct?: number | null
    isIncreaseBad?: boolean | null
}

export interface WebQueryResponseApi {
    results?: unknown
    /** `WebStatsTableQuery` and `WebExternalClicksTableQuery`: `context.columns.*` names, one per result cell. */
    columns?: unknown[] | null
    hasMore?: boolean | null
    last_refresh?: string | null
    cache_target_age?: string | null
    next_allowed_client_refresh?: string | null
    is_cached?: boolean
    timezone?: string | null
    resolved_date_range?: ResolvedDateRangeApi | null
    query_status?: QueryStatusFieldsApi | null
}

export interface WebOverviewResponseApi extends WebQueryResponseApi {
    results?: WebOverviewItemApi[]
}

export type WebInterval = 'hour' | 'day' | 'week' | 'month'

export interface WebQueryWindow {
    dateFrom: string | null
    dateTo: string | null
    explicitDate?: boolean
    interval?: WebInterval
    properties?: readonly WebPropertyFilter[]
}

export interface WebOverviewQueryOptions extends WebQueryWindow {
    compare: boolean
    filterTestAccounts?: boolean
}

function dateRange(window: WebQueryWindow): Record<string, unknown> {
    return {
        date_from: window.dateFrom,
        date_to: window.dateTo,
        ...(window.explicitDate ? { explicitDate: true } : {}),
    }
}

/** The web's own query tags, so the server files these reads under web analytics as it does for the web's tiles. */
const WEB_ANALYTICS_TAGS = { productKey: 'web_analytics' }

/** The web's overview tile query. Without filters it is the web's default, so the two share a cache entry. */
export function webOverviewQuery(options: WebOverviewQueryOptions): Record<string, unknown> {
    const { compare, interval = 'day', filterTestAccounts = false, properties = [] } = options
    return {
        kind: 'WebOverviewQuery',
        properties: [...properties],
        dateRange: dateRange(options),
        interval,
        compareFilter: { compare },
        filterTestAccounts,
    }
}

interface TrendSeries {
    math: string
    name: string
    customName: string
    mathProperty?: string
    axisFormat?: string
}

// The web's graph tile series. Session duration has no axis format on the web; the phone adds one so its axis and
// tooltip read as a duration, like the overview number.
const TREND_SERIES: Record<WebTrendMetric, TrendSeries> = {
    visitors: { math: 'dau', name: 'Pageview', customName: 'Unique visitors' },
    views: { math: 'total', name: 'Pageview', customName: 'Page views' },
    sessions: { math: 'unique_session', name: 'Pageview', customName: 'Sessions' },
    'session duration': {
        math: 'avg',
        name: 'Session duration',
        customName: 'Average session duration',
        mathProperty: '$session_duration',
        axisFormat: 'duration',
    },
    'bounce rate': {
        math: 'avg',
        name: 'Bounce rate',
        customName: 'Average bounce rate',
        mathProperty: '$is_bounce',
        axisFormat: 'percentage_scaled',
    },
}

export function webTrendQuery(options: WebQueryWindow & { metric: WebTrendMetric }): Record<string, unknown> {
    const series = TREND_SERIES[options.metric]
    return {
        kind: 'TrendsQuery',
        dateRange: dateRange(options),
        interval: options.interval ?? 'day',
        series: [
            {
                kind: 'EventsNode',
                event: '$pageview',
                math: series.math,
                name: series.name,
                custom_name: series.customName,
                ...(series.mathProperty
                    ? { math_property: series.mathProperty, math_property_type: 'session_properties' }
                    : {}),
            },
        ],
        trendsFilter: {
            display: 'ActionsLineGraph',
            ...(series.axisFormat ? { aggregationAxisFormat: series.axisFormat } : {}),
        },
        compareFilter: { compare: true },
        filterTestAccounts: false,
        properties: [...(options.properties ?? [])],
        tags: WEB_ANALYTICS_TAGS,
    }
}

/** Outbound clicks use the web's own `WebExternalClicksTableQuery`, which counts clicks instead of views. */
export function webBreakdownQuery(
    options: WebQueryWindow & { breakdown: WebBreakdown; limit: number }
): Record<string, unknown> {
    const shared = {
        dateRange: dateRange(options),
        properties: [...(options.properties ?? [])],
        compareFilter: { compare: true },
        filterTestAccounts: false,
        limit: options.limit,
    }
    if (options.breakdown === 'ExitClick') {
        return { kind: 'WebExternalClicksTableQuery', ...shared }
    }
    return { kind: 'WebStatsTableQuery', breakdownBy: options.breakdown, ...shared }
}

export function webRetentionQuery(options: WebQueryWindow): Record<string, unknown> {
    return {
        kind: 'RetentionQuery',
        properties: [...(options.properties ?? [])],
        dateRange: dateRange(options),
        filterTestAccounts: false,
        retentionFilter: {
            retentionType: 'retention_first_time',
            retentionReference: 'total',
            totalIntervals: 5,
            period: 'Week',
        },
        tags: WEB_ANALYTICS_TAGS,
    }
}

/** As on the web, the filters sit on the series, and visitors count in the hour their session started. */
export function webActiveHoursQuery(options: WebQueryWindow): Record<string, unknown> {
    return {
        kind: 'TrendsQuery',
        series: [
            {
                kind: 'EventsNode',
                event: '$pageview',
                name: '$pageview',
                math: 'dau',
                properties: [...(options.properties ?? [])],
            },
        ],
        dateRange: dateRange(options),
        trendsFilter: { display: 'CalendarHeatmap' },
        calendarHeatmapFilter: { bucketBySessionStart: true },
        tags: WEB_ANALYTICS_TAGS,
    }
}

/** One `POST query/` with no polling: a response that still runs keeps the old value until the next due check. */
export async function fetchWebQuery(
    query: Record<string, unknown>,
    options: { refresh: QueryRefresh; signal?: AbortSignal }
): Promise<WebQueryResponseApi> {
    return (await runQuery(query, {
        refresh: options.refresh,
        poll: false,
        signal: options.signal,
    })) as WebQueryResponseApi
}

export async function fetchWebOverview(
    query: Record<string, unknown>,
    options: { refresh: QueryRefresh; signal?: AbortSignal }
): Promise<WebOverviewResponseApi> {
    return (await fetchWebQuery(query, options)) as WebOverviewResponseApi
}
