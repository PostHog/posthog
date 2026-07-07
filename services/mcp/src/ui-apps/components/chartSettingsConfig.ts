import type { YAxisFormat } from '@posthog/quill-charts'

import type { ChartDisplayType, TrendsFilter } from './types'

export type ChartType = 'line' | 'area' | 'bar' | 'stacked-bar' | 'slope'

// Reuse quill's canonical y-unit union so the two can't drift.
export type YUnit = YAxisFormat

export interface ChartConfig {
    showValueLabels: boolean
    showTrendLine: boolean
    showConfidenceIntervals: boolean
    confidenceLevel: number
    percentStack: boolean
    yUnit: YUnit
}

export const DEFAULT_CHART_CONFIG: ChartConfig = {
    showValueLabels: false,
    showTrendLine: false,
    showConfidenceIntervals: false,
    confidenceLevel: 95,
    percentStack: false,
    yUnit: 'numeric',
}

export const Y_UNIT_OPTIONS: { value: YUnit; label: string }[] = [
    { value: 'numeric', label: 'Numeric' },
    { value: 'short', label: 'Compact (1.2K)' },
    { value: 'percentage', label: 'Percentage (0–100)' },
    { value: 'percentage_scaled', label: 'Percentage (0–1)' },
    { value: 'duration', label: 'Duration (s)' },
    { value: 'duration_ms', label: 'Duration (ms)' },
    { value: 'currency', label: 'Currency' },
]

export function chartConfigFromTrendsFilter(trendsFilter: TrendsFilter | undefined): ChartConfig {
    return {
        showValueLabels: trendsFilter?.showValuesOnSeries ?? DEFAULT_CHART_CONFIG.showValueLabels,
        showTrendLine: trendsFilter?.showTrendLines ?? DEFAULT_CHART_CONFIG.showTrendLine,
        showConfidenceIntervals: trendsFilter?.showConfidenceIntervals ?? DEFAULT_CHART_CONFIG.showConfidenceIntervals,
        confidenceLevel: trendsFilter?.confidenceLevel ?? DEFAULT_CHART_CONFIG.confidenceLevel,
        percentStack: trendsFilter?.showPercentStackView ?? DEFAULT_CHART_CONFIG.percentStack,
        yUnit: trendsFilter?.aggregationAxisFormat ?? DEFAULT_CHART_CONFIG.yUnit,
    }
}

export function defaultChartType(displayType: ChartDisplayType): ChartType {
    if (displayType === 'SlopeGraph') {
        return 'slope'
    }
    if (displayType === 'ActionsAreaGraph') {
        return 'area'
    }
    if (displayType === 'ActionsUnstackedBar') {
        return 'bar'
    }
    // ActionsBar renders stacked on web, so map it to the stacked option.
    if (displayType === 'ActionsBar' || displayType === 'ActionsStackedBar') {
        return 'stacked-bar'
    }
    return 'line'
}

export function isBarFamily(chartType: ChartType): boolean {
    return chartType === 'bar' || chartType === 'stacked-bar'
}

export function supportsPercentStack(chartType: ChartType): boolean {
    return chartType === 'area' || chartType === 'stacked-bar'
}

export interface ResolvedChartView {
    slopeAvailable: boolean
    effectiveType: ChartType
}

// Slope needs at least two time points; below that it falls back to line.
export function resolveChartView(chartType: ChartType, labelCount: number): ResolvedChartView {
    const slopeAvailable = labelCount >= 2
    return { slopeAvailable, effectiveType: chartType === 'slope' && !slopeAvailable ? 'line' : chartType }
}
