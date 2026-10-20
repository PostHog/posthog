import { asRecord } from '@/lib/records'
import type { RangeChoice, SavedRange } from '@/model/views'

import { type RangeValues, rangeValues } from './rangePresets'

/**
 * Compare on dashboards needs a server build that accepts `compareFilter` in a dashboard `filters_override`
 * (`DashboardFilter` forbids unknown keys, so an older build rejects it). Turn this on only after checking that US
 * and EU run such a build. While it is false, the range sheet shows the compare toggle disabled with its note.
 */
export const DASHBOARD_COMPARE_SUPPORTED = false

/** A `DashboardFilter` sent as `filters_override`. */
export type FiltersOverride = Record<string, unknown>

/**
 * The override for a range choice, or null to read the saved range. It always carries `date_to`, also as null:
 * the server merges by top-level key, so a missing `date_to` would keep the saved end date.
 */
export function rangeOverride(choice: RangeChoice | null): FiltersOverride | null {
    if (!choice) {
        return null
    }
    const values = rangeValues(choice)
    return {
        date_from: values.date_from,
        date_to: values.date_to,
        ...(values.explicitDate === undefined ? {} : { explicitDate: values.explicitDate }),
    }
}

/** The dashboard override, with compare only when the server accepts it. */
export function dashboardOverride(choice: RangeChoice | null, compare: boolean): FiltersOverride | null {
    const base = rangeOverride(choice)
    if (!compare || !DASHBOARD_COMPARE_SUPPORTED || !compareAllowed(choice ? rangeValues(choice).date_from : null)) {
        return base
    }
    return { ...(base ?? {}), compareFilter: { compare: true } }
}

/**
 * The override one tile reads with. A SQL tile without `{filters}` ignores the range, but the override still changes
 * its cache key, so each new range would be a cold compute with the same numbers. It reads without one.
 */
export function overrideForTile(
    tile: { ignoresRangeOverride: boolean },
    override: FiltersOverride | null
): FiltersOverride | null {
    return tile.ignoresRangeOverride ? null : override
}

/** With `date_from: "all"` the server turns compare off for every query kind. */
export function compareAllowed(dateFrom: string | null): boolean {
    return dateFrom !== 'all'
}

export function supportsCompare(query: unknown): boolean {
    const node = asRecord(query)
    return (asRecord(node?.source) ?? node)?.kind === 'TrendsQuery'
}

/**
 * The `POST query/` body for "Compare to previous period" on an insight: the response's `query.source` with compare
 * set to the requested state and chosen range, or the saved range when there is no choice. Null when unsupported.
 */
export function compareQuery(
    query: unknown,
    choice: RangeChoice | null,
    compare = true
): Record<string, unknown> | null {
    const node = asRecord(query)
    const source = asRecord(node?.source) ?? node
    if (!source || !supportsCompare(query)) {
        return null
    }
    const savedRange = asRecord(source.dateRange)
    const dateRange: Record<string, unknown> = choice ? { ...rangeValues(choice) } : { ...(savedRange ?? {}) }
    const dateFrom = typeof dateRange.date_from === 'string' ? dateRange.date_from : null
    if (compare && !compareAllowed(dateFrom)) {
        return null
    }
    return { ...source, compareFilter: { compare }, dateRange }
}

/** The web analytics `dateRange` for a choice, or the web's default range of the last 7 days. */
export function webAnalyticsRange(choice: RangeChoice | null): RangeValues {
    return choice ? rangeValues(choice) : { date_from: '-7d', date_to: null }
}

export const WEB_ANALYTICS_SAVED_RANGE: SavedRange = { dateFrom: '-7d', dateTo: null }
