import type { ChartDisplayType, TrendsFilter } from './types'

export type ChartType = 'line' | 'area' | 'bar' | 'stacked-bar' | 'slope'

// Mirrors quill-charts `YAxisFormat` structurally — declared as literals so this module stays
// runtime-import-free and unit-testable in the node vitest project.
export type YUnit = 'numeric' | 'short' | 'percentage' | 'percentage_scaled' | 'duration' | 'duration_ms' | 'currency'

export interface ChartConfig {
    showValueLabels: boolean
    showTrendLine: boolean
    showMovingAverage: boolean
    /** Seeded from the query only — not exposed in the options dialog. */
    movingAverageIntervals: number
    showConfidenceIntervals: boolean
    /** Seeded from the query only — not exposed in the options dialog. */
    confidenceLevel: number
    percentStack: boolean
    yUnit: YUnit
}

export const DEFAULT_CHART_CONFIG: ChartConfig = {
    showValueLabels: false,
    showTrendLine: false,
    showMovingAverage: false,
    movingAverageIntervals: 7,
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

/** Initial options for a chart: the saved insight's trendsFilter where present, defaults otherwise. */
export function chartConfigFromTrendsFilter(trendsFilter: TrendsFilter | undefined): ChartConfig {
    return {
        showValueLabels: trendsFilter?.showValuesOnSeries ?? DEFAULT_CHART_CONFIG.showValueLabels,
        showTrendLine: trendsFilter?.showTrendLines ?? DEFAULT_CHART_CONFIG.showTrendLine,
        showMovingAverage: trendsFilter?.showMovingAverage ?? DEFAULT_CHART_CONFIG.showMovingAverage,
        // `||` (not `??`): a 0 window would make buildDerivedConfigs emit no-op averages.
        movingAverageIntervals: trendsFilter?.movingAverageIntervals || DEFAULT_CHART_CONFIG.movingAverageIntervals,
        showConfidenceIntervals: trendsFilter?.showConfidenceIntervals ?? DEFAULT_CHART_CONFIG.showConfidenceIntervals,
        confidenceLevel: trendsFilter?.confidenceLevel ?? DEFAULT_CHART_CONFIG.confidenceLevel,
        percentStack: trendsFilter?.showPercentStackView ?? DEFAULT_CHART_CONFIG.percentStack,
        yUnit: trendsFilter?.aggregationAxisFormat ?? DEFAULT_CHART_CONFIG.yUnit,
    }
}

export function defaultChartType(displayType: ChartDisplayType): ChartType {
    // The backend slope runner returns two points per series, so open straight into slope mode.
    if (displayType === 'SlopeGraph') {
        return 'slope'
    }
    if (displayType === 'ActionsAreaGraph') {
        return 'area'
    }
    if (displayType === 'ActionsUnstackedBar') {
        return 'bar'
    }
    // ActionsBar has always rendered stacked (web parity), so it maps to the stacked option.
    if (displayType === 'ActionsBar' || displayType === 'ActionsStackedBar') {
        return 'stacked-bar'
    }
    return 'line'
}

export function isBarFamily(chartType: ChartType): boolean {
    return chartType === 'bar' || chartType === 'stacked-bar'
}

/** Web parity: percent stack is only meaningful for stacked renderings (area auto-stacks, stacked bars). */
export function supportsPercentStack(chartType: ChartType): boolean {
    return chartType === 'area' || chartType === 'stacked-bar'
}
