import type { QueryStatusFieldsApi, ResolvedDateRangeApi } from './insights'
import { type QueryRefresh, runQuery } from './query'

// Shapes follow `WebOverviewQuery`, `WebOverviewItem` and `CachedWebOverviewQueryResponse` in `posthog/schema.py`.

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

export interface WebOverviewResponseApi {
    results?: WebOverviewItemApi[]
    last_refresh?: string | null
    cache_target_age?: string | null
    next_allowed_client_refresh?: string | null
    is_cached?: boolean
    timezone?: string | null
    resolved_date_range?: ResolvedDateRangeApi | null
    query_status?: QueryStatusFieldsApi | null
}

export interface WebOverviewQueryOptions {
    dateFrom: string | null
    dateTo: string | null
    explicitDate?: boolean
    compare: boolean
    interval?: 'hour' | 'day' | 'week' | 'month'
    filterTestAccounts?: boolean
}

/** The web's overview tile query without its property filters, so a phone read with the web's range can share its cache. */
export function webOverviewQuery(options: WebOverviewQueryOptions): Record<string, unknown> {
    const { dateFrom, dateTo, explicitDate, compare, interval = 'day', filterTestAccounts = false } = options
    return {
        kind: 'WebOverviewQuery',
        properties: [],
        dateRange: { date_from: dateFrom, date_to: dateTo, ...(explicitDate ? { explicitDate: true } : {}) },
        interval,
        compareFilter: { compare },
        filterTestAccounts,
    }
}

/** One `POST query/` with no polling: a response that still runs keeps the old value until the next due check. */
export async function fetchWebOverview(
    query: Record<string, unknown>,
    options: { refresh: QueryRefresh; signal?: AbortSignal }
): Promise<WebOverviewResponseApi> {
    return (await runQuery(query, {
        refresh: options.refresh,
        poll: false,
        signal: options.signal,
    })) as WebOverviewResponseApi
}
