import { apiJson, projectPath } from './client'
import type { InsightApi } from './insights'
import type { PaginatedApi } from './reports'

// Shapes follow `DashboardBasicSerializer`, `DashboardSerializer` and `DashboardTileSerializer` in
// `products/dashboards/backend/api/dashboard.py`, keeping the fields the app reads.

export interface DashboardBasicApi {
    id: number
    name: string | null
    description?: string | null
    pinned?: boolean
    /** This user's last web view. Null for a dashboard the user never viewed; the list then sorts it by creation. */
    last_viewed_at?: string | null
    last_refresh?: string | null
    created_at?: string | null
    deleted?: boolean
}

export interface DashboardTileApi {
    id: number
    /** A full `InsightSerializer` with the cached result. Null for text and button tiles. */
    insight: InsightApi | null
    text?: { body?: string | null } | null
    /** `sm` (12 columns) and `xs` (1 column) grid positions. */
    layouts?: Record<string, { x?: number; y?: number; w?: number; h?: number } | undefined> | null
    /** Tile-level filters. They win over the dashboard and the request override. */
    filters_overrides?: Record<string, unknown> | null
    deleted?: boolean | null
}

export interface DashboardApi extends DashboardBasicApi {
    tiles?: DashboardTileApi[] | null
    /** The saved filters with the request's `filters_override` applied. */
    filters?: Record<string, unknown> | null
    /** The saved filters alone, also on a read with an override. Null when the dashboard saved none. */
    persisted_filters?: Record<string, unknown> | null
    /** Shared by every viewer and set by the web's bulk refresh. The app reads it and never writes it. */
    last_refresh?: string | null
}

export interface DashboardReadOptions {
    /** A `DashboardFilter`, sent as JSON. Null reads the saved filters. */
    filtersOverride?: Record<string, unknown> | null
    signal?: AbortSignal
}

/**
 * `GET dashboards/{id}/?refresh=force_cache`: cached tiles only, no compute. The explicit value keeps paints
 * cache-only even if the server default changes.
 */
export function fetchDashboard(id: number, options: DashboardReadOptions = {}): Promise<DashboardApi> {
    const { filtersOverride, signal } = options
    return apiJson<DashboardApi>(projectPath(`dashboards/${id}/`), {
        query: {
            refresh: 'force_cache',
            filters_override: filtersOverride ? JSON.stringify(filtersOverride) : undefined,
        },
        signal,
    })
}

export const DASHBOARD_PAGE_SIZE = 30
export const RECENT_DASHBOARD_LIMIT = 10
export const DASHBOARD_SEARCH_LIMIT = 10

/** Browse, Dashboards, in the web Views order. */
export function fetchDashboardPage(offset: number, signal?: AbortSignal): Promise<PaginatedApi<DashboardBasicApi>> {
    return apiJson<PaginatedApi<DashboardBasicApi>>(projectPath('dashboards/'), {
        query: { ordering: '-last_viewed_at', limit: DASHBOARD_PAGE_SIZE, offset },
        signal,
    })
}

/** The dashboards this user viewed on the web, newest first. Rows with no `last_viewed_at` were never viewed. */
export function fetchRecentDashboards(signal?: AbortSignal): Promise<PaginatedApi<DashboardBasicApi>> {
    return apiJson<PaginatedApi<DashboardBasicApi>>(projectPath('dashboards/'), {
        query: { ordering: '-last_viewed_at', limit: RECENT_DASHBOARD_LIMIT },
        signal,
    })
}

export function searchDashboards(search: string, signal?: AbortSignal): Promise<PaginatedApi<DashboardBasicApi>> {
    return apiJson<PaginatedApi<DashboardBasicApi>>(projectPath('dashboards/'), {
        query: { search, limit: DASHBOARD_SEARCH_LIMIT },
        signal,
    })
}
