import type { TrendsQuery, InsightVizNode, ChartDisplayType, FunnelResult } from './types'

type TrendsQueryLike = TrendsQuery | InsightVizNode

export function getDisplayType(query: TrendsQueryLike): ChartDisplayType {
    if (query.kind === 'InsightVizNode' && query.source.kind === 'TrendsQuery') {
        return query.source.trendsFilter?.display || 'ActionsLineGraph'
    }
    if (query.kind === 'TrendsQuery') {
        return query.trendsFilter?.display || 'ActionsLineGraph'
    }
    return 'ActionsLineGraph'
}

export function isBarChart(displayType: ChartDisplayType): boolean {
    return displayType === 'ActionsBar' || displayType === 'ActionsBarValue'
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

export function formatDate(dateStr: string): string {
    const date = new Date(dateStr)
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function getSeriesLabel(item: { label?: string; action?: { name?: string } }, index: number): string {
    return item.label || item.action?.name || `Series ${index + 1}`
}

export function normalizeFunnelSteps(results: FunnelResult): Array<{ name: string; count: number; order: number }> {
    if (results.length === 0) return []

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
