import type { YAxisFormat } from '@posthog/quill-charts'

import type { ChartDisplayType, TrendsFilter } from './types'

export type ChartType = 'line' | 'area' | 'bar' | 'stacked-bar' | 'slope'

// The canonical y-unit union lives in quill-charts; reuse it so the two never drift. `import type`
// is erased at build time, so this stays runtime-free and unit-testable in the node vitest project.
export type YUnit = YAxisFormat

export interface ChartConfig {
    showValueLabels: boolean
    showTrendLine: boolean
    showConfidenceIntervals: boolean
    /** Seeded from the query only — not exposed in the options dialog. */
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

/** Initial options for a chart: the saved insight's trendsFilter where present, defaults otherwise. */
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

export interface ResolvedChartView {
    /** Whether the slope option should be offered — it needs at least two time points. */
    slopeAvailable: boolean
    /** Chart type to actually render; slope falls back to line when fewer than two points remain. */
    effectiveType: ChartType
}

// Slope needs a start and an end, so it's only available with >= 2 time points; a chart that drops
// below two points after slope was picked falls back to line rather than rendering blank.
export function resolveChartView(chartType: ChartType, labelCount: number): ResolvedChartView {
    const slopeAvailable = labelCount >= 2
    return { slopeAvailable, effectiveType: chartType === 'slope' && !slopeAvailable ? 'line' : chartType }
}
