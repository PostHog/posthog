import type { Series } from '@posthog/quill-charts'

import type {
    ChartDisplayType,
    FunnelResult,
    HogQLResult,
    TrendsQuery,
    TrendsResultItem,
    WebOverviewItem,
} from './types'

export function getDisplayType(query: TrendsQuery | undefined): ChartDisplayType {
    return query?.trendsFilter?.display || 'ActionsLineGraph'
}

export interface InsightQueryProperties {
    queryKind?: string
    querySourceKind?: string
    display?: string
    funnelVizType?: string
}

export function insightQueryProperties(query: unknown): InsightQueryProperties {
    if (typeof query !== 'object' || query === null) {
        return {}
    }
    const node = query as Record<string, unknown>
    const hasSource = typeof node.source === 'object' && node.source !== null
    const source = (hasSource ? node.source : node) as Record<string, any>
    const defaultDisplay =
        source.kind === 'TrendsQuery' || source.kind === 'StickinessQuery' ? 'ActionsLineGraph' : undefined
    return {
        queryKind: typeof node.kind === 'string' ? node.kind : undefined,
        querySourceKind: hasSource && typeof source.kind === 'string' ? source.kind : undefined,
        display: source.trendsFilter?.display ?? source.stickinessFilter?.display ?? defaultDisplay,
        funnelVizType: source.funnelsFilter?.funnelVizType,
    }
}

export function formatNumber(value: number): string {
    if (value >= 1_000_000) {
        return `${(value / 1_000_000).toFixed(1)}M`
    }
    if (value >= 1_000) {
        return `${(value / 1_000).toFixed(1)}K`
    }
    return value.toLocaleString()
}

export function formatPercent(value: number): string {
    return `${(value * 100).toFixed(1)}%`
}

/** Format a duration given in milliseconds as the two most-significant units (e.g. `1d 3h`, `34m 43s`). */
export function formatDuration(ms: number): string {
    if (!isFinite(ms) || ms <= 0) {
        return '0s'
    }
    const totalSeconds = Math.round(ms / 1000)
    const units: Array<[number, string]> = [
        [Math.floor(totalSeconds / 86400), 'd'],
        [Math.floor((totalSeconds % 86400) / 3600), 'h'],
        [Math.floor((totalSeconds % 3600) / 60), 'm'],
        [totalSeconds % 60, 's'],
    ]
    const parts = units.filter(([value]) => value > 0).map(([value, unit]) => `${value}${unit}`)
    return parts.slice(0, 2).join(' ') || '0s'
}

// Only format strings that look like ISO dates — `new Date(...)` is permissive enough that
// labels like "Day 1" silently parse to Jan 1 2001, mangling pre-formatted axis labels.
const ISO_DATE_PREFIX = /^\d{4}-\d{2}-\d{2}/

export function formatDate(dateStr: string): string {
    if (!ISO_DATE_PREFIX.test(dateStr)) {
        return dateStr
    }
    const date = new Date(dateStr)
    if (Number.isNaN(date.getTime())) {
        return dateStr
    }
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function formatTooltipDate(dateStr: string): string {
    if (!ISO_DATE_PREFIX.test(dateStr)) {
        return dateStr
    }
    const date = new Date(dateStr)
    if (Number.isNaN(date.getTime())) {
        return dateStr
    }
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export function getSeriesLabel(item: { label?: string; action?: { name?: string } }, index: number): string {
    return item.label || item.action?.name || `Series ${index + 1}`
}

export function buildProportionBarSeries(results: TrendsResultItem[], getColor: (index: number) => string): Series[] {
    // One bar has one total, so a previous period saved with compare on is left out.
    return results
        .filter((item) => item.compare_label !== 'previous')
        .map((item, i) => ({
            key: String(i),
            label: getSeriesLabel(item, i),
            data: [item.aggregated_value ?? 0],
            color: getColor(i),
        }))
}

export function normalizeFunnelSteps(results: FunnelResult): Array<{ name: string; count: number; order: number }> {
    if (results.length === 0) {
        return []
    }

    const firstItem = results[0]
    if (Array.isArray(firstItem)) {
        return firstItem.map((step, idx) => ({
            name: step.custom_name || step.name || `Step ${idx + 1}`,
            count: step.count || 0,
            order: step.order ?? idx,
        }))
    }

    return (results as Array<{ name?: string; custom_name?: string; count?: number; order?: number }>).map(
        (step, idx) => ({
            name: step.custom_name || step.name || `Step ${idx + 1}`,
            count: step.count || 0,
            order: step.order ?? idx,
        })
    )
}

// Web stats columns that drive the web analytics UI only, not data.
const HIDDEN_WEB_STATS_COLUMNS = new Set(['ui_fill_fraction', 'cross_sell'])

function humanizeKey(key: string): string {
    const text = key.replace(/_/g, ' ')
    return text.charAt(0).toUpperCase() + text.slice(1)
}

function formatWebOverviewValue({ kind, value }: WebOverviewItem): string | null {
    if (value === null || value === undefined) {
        return null
    }
    if (kind === 'percentage') {
        return `${value.toFixed(1)}%`
    }
    if (kind === 'duration_s') {
        return formatDuration(value * 1000)
    }
    return formatNumber(value)
}

function webStatsCell(column: string, value: unknown): unknown {
    // Metric cells are `[current, previous]` tuples; multi-part breakdowns (city, region) are tuples too.
    if (Array.isArray(value) && column === 'breakdown_value') {
        return value.filter((part) => part !== null && part !== '').join(', ')
    }
    const current = Array.isArray(value) ? value[0] : value
    return typeof current === 'number' && /rate|percentage/.test(column) ? formatPercent(current) : current
}

/** Maps query results that have no chart of their own into the `columns`/`results` shape of the table. */
export function toTableResult(query: unknown, results: unknown, columns: string[] | undefined): HogQLResult {
    const node = (query ?? {}) as { kind?: unknown; breakdownBy?: unknown }
    if (node.kind === 'WebOverviewQuery' && Array.isArray(results)) {
        return {
            columns: ['Metric', 'Value', 'Change'],
            results: (results as WebOverviewItem[]).map((item) => [
                humanizeKey(item.key),
                formatWebOverviewValue(item),
                typeof item.changeFromPreviousPct === 'number'
                    ? `${item.changeFromPreviousPct > 0 ? '+' : ''}${item.changeFromPreviousPct}%`
                    : null,
            ]),
        }
    }
    if (node.kind === 'WebStatsTableQuery' && Array.isArray(results)) {
        const names = (columns ?? []).map((column) => column.replace(/^context\.columns\./, ''))
        const kept = names.flatMap((name, index) => (HIDDEN_WEB_STATS_COLUMNS.has(name) ? [] : [index]))
        return {
            columns: kept.map((index) =>
                names[index] === 'breakdown_value' && typeof node.breakdownBy === 'string'
                    ? node.breakdownBy
                    : humanizeKey(names[index]!)
            ),
            results: (results as unknown[][]).map((row) =>
                kept.map((index) => webStatsCell(names[index]!, row[index]))
            ),
        }
    }
    return results as HogQLResult
}
