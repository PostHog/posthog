import { ApiError, apiJson, projectPath } from './client'
import type { PaginatedApi } from './reports'

// Shapes follow `InsightSerializer` and `InsightBasicSerializer` in
// `products/product_analytics/backend/presentation/insight.py`, keeping the fields the app reads.

/**
 * `force_cache` reads the cache only. `blocking` computes only past `cache_target_age` or on a miss. `force_blocking`
 * always computes, so the app sends it only once `next_allowed_client_refresh` has passed.
 * Never `async_except_on_cache_miss`: the insight endpoint turns it into a cache-only read.
 */
export type InsightRefresh = 'force_cache' | 'blocking' | 'force_blocking'

export interface QueryStatusFieldsApi {
    id?: string
    complete?: boolean | null
    error?: boolean | null
    /** `rate_limited` when the org's query slots are full. The response then carries `result: null`. */
    error_code?: string | null
    error_message?: string | null
}

export interface ResolvedDateRangeApi {
    date_from: string
    date_to: string
}

export interface UserBasicApi {
    first_name?: string
    last_name?: string
    email?: string
}

export interface InsightApi {
    id: number
    short_id: string
    name: string | null
    derived_name: string | null
    description?: string | null
    /** The query with the dashboard and tile layers applied when the request named `from_dashboard`. */
    query: unknown
    result: unknown
    /** Also set to now on a rate-limited error response, so only a response with a result may be trusted. */
    last_refresh: string | null
    cache_target_age: string | null
    next_allowed_client_refresh: string | null
    is_cached?: boolean
    query_status?: QueryStatusFieldsApi | null
    timezone?: string | null
    resolved_date_range?: ResolvedDateRangeApi | null
    /** SQL insights only: the result's column names, and `[expression, clickhouseType]` per column. */
    columns?: string[] | null
    types?: [string, string][] | null
    /** SQL insights only: the server cut the result at its limit. */
    hasMore?: boolean | null
    created_by?: UserBasicApi | null
    created_at?: string | null
    last_modified_at?: string | null
    deleted?: boolean
}

export interface InsightBasicApi {
    id: number
    short_id: string
    name: string | null
    derived_name: string | null
    description?: string | null
    query?: unknown
    last_refresh?: string | null
    last_modified_at?: string | null
    last_viewed_at?: string | null
    deleted?: boolean
}

export interface InsightReadOptions {
    refresh: InsightRefresh
    /** Applies the dashboard's filters and the tile's overrides, and takes a dashboard query slot on a compute. */
    fromDashboard?: number | null
    /** A `DashboardFilter`, sent as JSON. */
    filtersOverride?: Record<string, unknown> | null
    signal?: AbortSignal
}

/** `GET insights/{id}/`. Takes the numeric id or the `short_id`; an all-digit value is tried as an id first. */
export function fetchInsight(idOrShortId: number | string, options: InsightReadOptions): Promise<InsightApi> {
    const { refresh, fromDashboard, filtersOverride, signal } = options
    return apiJson<InsightApi>(projectPath(`insights/${encodeURIComponent(String(idOrShortId))}/`), {
        query: {
            refresh,
            from_dashboard: fromDashboard ?? undefined,
            filters_override: filtersOverride ? JSON.stringify(filtersOverride) : undefined,
        },
        signal,
    })
}

/** `GET insights/?short_id=` with a cache-only read, for an all-digit `short_id` that retrieve resolved as an id. */
export async function fetchInsightByShortId(shortId: string, signal?: AbortSignal): Promise<InsightApi | undefined> {
    const page = await apiJson<PaginatedApi<InsightApi>>(projectPath('insights/'), {
        query: { short_id: shortId, refresh: 'force_cache' },
        signal,
    })
    return page.results.find((insight) => insight.short_id === shortId)
}

const ALL_DIGITS = /^\d+$/

/**
 * Reads an insight by its numeric id when known, else by `short_id`. Retrieve tries an all-digit `short_id` as a
 * primary key first, so a response for another insight falls back to the `short_id` filter once.
 */
export async function readInsight(
    target: { id?: number | null; shortId: string },
    options: InsightReadOptions
): Promise<InsightApi> {
    if (typeof target.id === 'number') {
        return fetchInsight(target.id, options)
    }
    const insight = await fetchInsight(target.shortId, options)
    if (insight.short_id === target.shortId || !ALL_DIGITS.test(target.shortId)) {
        return insight
    }
    return (await fetchInsightByShortId(target.shortId, options.signal)) ?? insight
}

export interface InsightSummary {
    name: string | null
    description: string | null
}

export async function getInsightSummary(shortId: string, signal?: AbortSignal): Promise<InsightSummary | null> {
    try {
        const insight = await fetchInsight(shortId, { refresh: 'force_cache', signal })
        return { name: insight.name || insight.derived_name || null, description: insight.description || null }
    } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null
        throw error
    }
}

export const INSIGHT_PAGE_SIZE = 30
export const INSIGHT_SEARCH_LIMIT = 10

export async function fetchInsightMetadata(
    shortId: string,
    signal?: AbortSignal
): Promise<InsightBasicApi | undefined> {
    const page = await apiJson<PaginatedApi<InsightBasicApi>>(projectPath('insights/'), {
        query: { basic: true, short_id: shortId, refresh: 'force_cache' },
        signal,
    })
    return page.results.find((insight) => insight.short_id === shortId)
}

/** Browse, Insights. `basic` drops the results, so a page is small. */
export function fetchInsightPage(offset: number, signal?: AbortSignal): Promise<PaginatedApi<InsightBasicApi>> {
    return apiJson<PaginatedApi<InsightBasicApi>>(projectPath('insights/'), {
        query: { basic: true, saved: true, order: '-last_modified_at', limit: INSIGHT_PAGE_SIZE, offset },
        signal,
    })
}

export function searchInsights(search: string, signal?: AbortSignal): Promise<PaginatedApi<InsightBasicApi>> {
    return apiJson<PaginatedApi<InsightBasicApi>>(projectPath('insights/'), {
        query: { basic: true, saved: true, search, limit: INSIGHT_SEARCH_LIMIT },
        signal,
    })
}

/** `POST insights/viewed/` once per insight open, so the web's "Last viewed" includes phone opens. */
export async function markInsightViewed(insightId: number): Promise<void> {
    await apiJson<unknown>(projectPath('insights/viewed/'), { method: 'POST', json: { insight_ids: [insightId] } })
}
