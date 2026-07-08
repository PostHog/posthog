import type { ChartDisplayType, FunnelResult, TrendsQuery } from './types'

export function getDisplayType(query: TrendsQuery | undefined): ChartDisplayType {
    return query?.trendsFilter?.display || 'ActionsLineGraph'
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
