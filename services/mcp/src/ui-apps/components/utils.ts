import type { Series } from '@posthog/quill-charts'

import type { ChartDisplayType, FunnelResult, TrendsQuery, TrendsResultItem } from './types'

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
    return {
        queryKind: typeof node.kind === 'string' ? node.kind : undefined,
        querySourceKind: hasSource && typeof source.kind === 'string' ? source.kind : undefined,
        // Only what the query set, so an unset display stays empty instead of looking like a pick.
        // SQL insights keep their display on the wrapper node, not on the HogQL source.
        display:
            source.trendsFilter?.display ??
            source.stickinessFilter?.display ??
            source.retentionFilter?.display ??
            (node.kind === 'DataVisualizationNode' && typeof node.display === 'string' ? node.display : undefined),
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
