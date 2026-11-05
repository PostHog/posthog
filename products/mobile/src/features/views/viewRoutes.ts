import type { QueryKey } from '@tanstack/react-query'
import type { Href } from 'expo-router'

import type { PinDisplayMode, ViewEntry, ViewRef } from '@/model/views'

const ENTRIES: readonly ViewEntry[] = ['pinned', 'recent', 'browse', 'search', 'deep_link', 'dashboard']
const MODES: readonly PinDisplayMode[] = ['row', 'number', 'chart']

/** How a view was opened. Sent with `mobile_view_opened`, so it travels in the route. */
export interface ViewOpenParams {
    from?: ViewEntry
    /** The pin's display mode, when opened from a pin. */
    mode?: PinDisplayMode | null
}

function openParams({ from, mode }: ViewOpenParams): Record<string, string> {
    return { ...(from ? { from } : {}), ...(mode ? { mode } : {}) }
}

/** `ref` is the pin or Browse row `ref`: the dashboard id as a string, or the demo ref. */
export function dashboardHref(ref: string, open: ViewOpenParams = {}): Href {
    return { pathname: '/views/dashboard/[id]', params: { id: ref, ...openParams(open) } }
}

export interface InsightRouteParams extends ViewOpenParams {
    /** Opened from a tile: the insight reads with `from_dashboard` and shares the dashboard's range. */
    fromDashboard?: string | null
    insightId?: number | null
}

export function insightHref(shortId: string, params: InsightRouteParams = {}): Href {
    const { fromDashboard, insightId, ...open } = params
    return {
        pathname: '/views/insight/[shortId]',
        params: {
            shortId,
            ...(fromDashboard ? { fromDashboard } : {}),
            ...(typeof insightId === 'number' ? { insightId: String(insightId) } : {}),
            ...openParams(open),
        },
    }
}

export function webAnalyticsHref(open: ViewOpenParams = {}): Href {
    return { pathname: '/views/web-analytics', params: openParams(open) }
}

/** The route of a native view, from a pin, Recent, Browse or search row. Null for kinds that open on the web. */
export function viewHref(view: Pick<ViewRef, 'kind' | 'ref'>, open: ViewOpenParams = {}): Href | null {
    switch (view.kind) {
        case 'dashboard':
            return view.ref ? dashboardHref(view.ref, open) : null
        case 'insight':
            return view.ref ? insightHref(view.ref, open) : null
        case 'web_analytics':
            return webAnalyticsHref(open)
        default:
            return null
    }
}

/**
 * The full-screen chart of an insight the phone already shows. `queryKey` names the snapshot's cache entry, so the
 * screen shows the same range, compare and tile layers. Without it the screen reads the insight's own entry.
 */
export function chartHref(shortId: string, queryKey: QueryKey | null): Href {
    return {
        pathname: '/views/chart/[shortId]',
        params: { shortId, ...(queryKey ? { key: JSON.stringify(queryKey) } : {}) },
    }
}

/** The cache key from `chartHref`, or null when the param is missing or is not a Views key. */
export function queryKeyParam(value: string | string[] | undefined): QueryKey | null {
    const first = Array.isArray(value) ? value[0] : value
    if (!first) {
        return null
    }
    try {
        const parsed: unknown = JSON.parse(first)
        return Array.isArray(parsed) && parsed[0] === 'views' ? parsed : null
    } catch {
        return null
    }
}

/** A deep link names no entry, so a missing or unknown `from` counts as `deep_link`. */
export function viewEntryParam(value: string | string[] | undefined): ViewEntry {
    const first = Array.isArray(value) ? value[0] : value
    return ENTRIES.find((entry) => entry === first) ?? 'deep_link'
}

export function displayModeParam(value: string | string[] | undefined): PinDisplayMode | null {
    const first = Array.isArray(value) ? value[0] : value
    return MODES.find((mode) => mode === first) ?? null
}

export function numberParam(value: string | string[] | undefined): number | null {
    const first = Array.isArray(value) ? value[0] : value
    const parsed = first ? Number(first) : Number.NaN
    return Number.isInteger(parsed) ? parsed : null
}
