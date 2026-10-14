import type { Href } from 'expo-router'

import type { PinDisplayMode, ViewEntry } from '@/model/views'

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
