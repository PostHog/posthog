import type { InsightApi } from '@/api/insights'
import type { WebQueryResponseApi } from '@/api/webAnalytics'
import { asRecord, isRecord } from '@/lib/records'

import type {
    Freshness,
    InsightSnapshot,
    ResolvedRange,
    WebActiveHoursSnapshot,
    WebBreakdown,
    WebBreakdownRow,
    WebBreakdownSnapshot,
    WebTrendMetric,
} from '../views'
import { hasGoodResult, insightSnapshot, type SnapshotContext } from './insightSnapshot'
import { breakdownFilter, breakdownValueLabel } from './webAnalyticsBreakdowns'

/** The `short_id` of the web analytics trend and retention snapshots, which are queries, not saved insights. */
export const WEB_ANALYTICS_SHORT_ID = 'web-analytics'

export const WEB_TREND_LABELS: Record<WebTrendMetric, string> = {
    visitors: 'Visitors',
    views: 'Page views',
    sessions: 'Sessions',
    'session duration': 'Session duration',
    'bounce rate': 'Bounce rate',
}

/** Revenue and conversion keys in the overview have no trend series. */
export function isWebTrendMetric(key: string): key is WebTrendMetric {
    return key in WEB_TREND_LABELS
}

function resolvedRangeOf(response: WebQueryResponseApi): ResolvedRange | null {
    const range = response.resolved_date_range
    return range?.date_from && range.date_to ? { from: range.date_from, to: range.date_to } : null
}

function freshnessOf(response: WebQueryResponseApi, readAt: number): Freshness {
    return {
        lastRefreshAt: response.last_refresh ?? null,
        cacheTargetAge: response.cache_target_age ?? null,
        nextAllowedRefreshAt: response.next_allowed_client_refresh ?? null,
        readAt,
        refreshFailed: false,
        dataReadAt: readAt,
    }
}

/** Same freshness rule as an insight: a response without a good result keeps the previous data. */
function keepOnBadResult<T extends Freshness>(
    response: WebQueryResponseApi,
    previous: T | undefined,
    readAt: number,
    empty: (failed: boolean) => T
): T | null {
    if (hasGoodResult(response)) {
        return null
    }
    const failed = Boolean(response.query_status?.error)
    if (previous) {
        return { ...previous, readAt, refreshFailed: failed || previous.refreshFailed }
    }
    return empty(failed)
}

function emptyFreshness(readAt: number, failed: boolean): Freshness {
    return {
        lastRefreshAt: null,
        cacheTargetAge: null,
        nextAllowedRefreshAt: null,
        readAt,
        refreshFailed: failed,
        dataReadAt: 0,
    }
}

/** Wraps a trends or retention answer as an insight, so the insight adapters, series and formatting apply. */
export function webInsightSnapshot(
    query: Record<string, unknown>,
    name: string,
    response: WebQueryResponseApi,
    previous: InsightSnapshot | undefined,
    context: SnapshotContext
): InsightSnapshot {
    const asInsight: InsightApi = {
        id: 0,
        short_id: WEB_ANALYTICS_SHORT_ID,
        name,
        derived_name: null,
        description: null,
        query: { kind: 'InsightVizNode', source: query },
        result: response.results ?? null,
        last_refresh: response.last_refresh ?? null,
        cache_target_age: response.cache_target_age ?? null,
        next_allowed_client_refresh: response.next_allowed_client_refresh ?? null,
        is_cached: response.is_cached,
        query_status: response.query_status,
        timezone: response.timezone,
        resolved_date_range: response.resolved_date_range,
    }
    return insightSnapshot(asInsight, previous, context)
}

const COLUMN_PREFIX = 'context.columns.'

function columnIndex(columns: readonly string[], ...names: string[]): number {
    return columns.findIndex((column) => names.includes(column))
}

function periodValues(cell: unknown): { current: number | null; previous: number | null } {
    const finite = (value: unknown): number | null =>
        typeof value === 'number' && Number.isFinite(value) ? value : null
    if (Array.isArray(cell)) {
        return { current: finite(cell[0]), previous: finite(cell[1]) }
    }
    return { current: finite(cell), previous: null }
}

const SECONDARY_LABELS: Record<string, string> = { views: 'Views', clicks: 'Clicks' }

/** Cells are found by column name, because the server adds columns (bounce rate, fill fraction) per query. */
export function webBreakdownSnapshot(
    breakdown: WebBreakdown,
    response: WebQueryResponseApi,
    previous: WebBreakdownSnapshot | undefined,
    readAt: number
): WebBreakdownSnapshot {
    const kept = keepOnBadResult(response, previous, readAt, (failed) => ({
        ...emptyFreshness(readAt, failed),
        breakdown,
        rows: [],
        secondaryLabel: null,
        hasMore: false,
        resolvedRange: null,
        computed: false,
    }))
    if (kept) {
        return kept
    }
    const columns = (Array.isArray(response.columns) ? response.columns : []).map((column) =>
        typeof column === 'string' && column.startsWith(COLUMN_PREFIX) ? column.slice(COLUMN_PREFIX.length) : ''
    )
    const valueAt = columnIndex(columns, 'breakdown_value', 'url')
    const visitorsAt = columnIndex(columns, 'visitors')
    const secondaryAt = columnIndex(columns, 'views', 'clicks')
    const results = Array.isArray(response.results) ? response.results : []
    const rows: WebBreakdownRow[] =
        valueAt < 0 || visitorsAt < 0
            ? []
            : results.flatMap((row, index): WebBreakdownRow[] => {
                  if (!Array.isArray(row)) {
                      return []
                  }
                  const raw = row[valueAt]
                  const visitors = periodValues(row[visitorsAt])
                  const { label, placeholder } = breakdownValueLabel(breakdown, raw)
                  return [
                      {
                          key: `${index}:${JSON.stringify(raw ?? null)}`,
                          label,
                          placeholder,
                          value: visitors.current ?? 0,
                          previous: visitors.previous,
                          secondary: secondaryAt < 0 ? null : periodValues(row[secondaryAt]).current,
                          filter: breakdownFilter(breakdown, raw),
                      },
                  ]
              })
    return {
        ...freshnessOf(response, readAt),
        breakdown,
        rows,
        secondaryLabel: secondaryAt < 0 ? null : (SECONDARY_LABELS[columns[secondaryAt] ?? ''] ?? null),
        hasMore: response.hasMore === true,
        resolvedRange: resolvedRangeOf(response),
        computed: response.is_cached === false,
    }
}

const DAYS = 7
const HOURS = 24

function emptyGrid(): number[][] {
    return Array.from({ length: DAYS }, () => Array.from({ length: HOURS }, () => 0))
}

/** `calendar_heatmap_data` rows are ISO weekdays (1 is Monday), in the project's timezone. */
export function webActiveHoursSnapshot(
    response: WebQueryResponseApi,
    previous: WebActiveHoursSnapshot | undefined,
    readAt: number
): WebActiveHoursSnapshot {
    const kept = keepOnBadResult(response, previous, readAt, (failed) => ({
        ...emptyFreshness(readAt, failed),
        cells: emptyGrid(),
        total: 0,
        resolvedRange: null,
        timezone: response.timezone ?? null,
        computed: false,
    }))
    if (kept) {
        return kept
    }
    const first = Array.isArray(response.results) ? asRecord(response.results[0]) : undefined
    const heatmap = asRecord(first?.calendar_heatmap_data)
    const cells = emptyGrid()
    let sum = 0
    for (const entry of Array.isArray(heatmap?.data) ? heatmap.data.filter(isRecord) : []) {
        const { row, column, value } = entry
        if (typeof row !== 'number' || typeof column !== 'number' || typeof value !== 'number') {
            continue
        }
        const day = cells[row - 1]
        if (day && column >= 0 && column < HOURS && Number.isFinite(value)) {
            day[column] = value
            sum += value
        }
    }
    const all = heatmap?.allAggregations
    return {
        ...freshnessOf(response, readAt),
        cells,
        // Unique visitors over the window are fewer than the sum of the hours, so the server's own total wins.
        total: typeof all === 'number' && Number.isFinite(all) ? all : sum,
        resolvedRange: resolvedRangeOf(response),
        timezone: response.timezone ?? null,
        computed: response.is_cached === false,
    }
}
