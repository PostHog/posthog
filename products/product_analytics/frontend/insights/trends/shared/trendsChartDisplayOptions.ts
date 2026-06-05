import type { TimeInterval, YAxisFormat } from '@posthog/quill-charts'

// Dependency-neutral display config shared by the web trends container and the MCP UI app.
// Deliberately free of `~/` and `lib/` imports (and kea) so it compiles in the MCP Vite
// bundle, which only resolves `products/*` and `@posthog/*`. The web side maps its kea-derived
// `TrendsFilter` into this; the MCP app builds one directly.

// Subset of `TrendsFilter` the y-axis formatter reads. `TrendsFilter` is structurally
// assignable to this, so web callers can pass it unchanged.
export interface YFormatterFields {
    aggregationAxisFormat?: YAxisFormat
    aggregationAxisPrefix?: string
    aggregationAxisPostfix?: string
    decimalPlaces?: number
    minDecimalPlaces?: number
}

// Structurally matches the schema `GoalLine`, without importing it.
export interface GoalLineLike {
    label: string
    value: number
    borderColor?: string
    displayLabel?: boolean
    displayIfCrossed?: boolean
    position?: 'start' | 'end'
}

// Confidence-interval helper signature. Injected (rather than imported from `lib/statistics`)
// so the transforms stay free of third-party stats deps the MCP bundle doesn't carry.
export type CiRangesFn = (data: number[], confidence: number) => [number[], number[]]

// Single source of truth for what the trends line chart can display.
export interface TrendsChartDisplayOptions {
    /** Area fill under each series (web: `display === ActionsAreaGraph`). */
    isArea?: boolean
    showMultipleYAxes?: boolean
    isPercentStackView?: boolean
    yAxisScaleType?: string | null
    interval?: TimeInterval | null
    timezone?: string
    /** Full date list for x-axis tick formatting; falls back to `labels`. */
    allDays?: string[]
    xAxisLabel?: string | null
    yAxisLabel?: string | null
    formatter?: YFormatterFields | null
    baseCurrency?: string
    showValuesOnSeries?: boolean
    showCrosshair?: boolean
    showConfidenceIntervals?: boolean
    confidenceLevel?: number
    showMovingAverage?: boolean
    movingAverageIntervals?: number
    showTrendLines?: boolean
}
