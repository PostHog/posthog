import type { TimeInterval, YAxisFormat } from '@posthog/quill-charts'

// Dependency-neutral display config shared by the web trends container and the MCP UI app.
// Deliberately free of `~/` and `lib/` imports (and kea) so it compiles in the MCP Vite
// bundle, which only resolves `products/*` and `@posthog/*`. The web side maps its kea-derived
// `TrendsFilter` into this; the MCP app builds one directly.

// Subset of the schema `TrendsFilter` the y-axis formatter reads. Declared structurally rather
// than imported as a deliberate firewall: this file is bundled into the MCP Vite app, which has
// no `~/` resolution, so importing `~/queries/schema/schema-general` would either break the build
// or force the entire generated-schema graph into the MCP typecheck. The real `TrendsFilter` is
// structurally assignable to this (asserted in trendsChartTransforms.test.ts), so web callers pass
// it unchanged.
export interface YFormatterFields {
    aggregationAxisFormat?: YAxisFormat
    aggregationAxisPrefix?: string
    aggregationAxisPostfix?: string
    decimalPlaces?: number
    minDecimalPlaces?: number
}

// Structural mirror of the schema `GoalLine`. Not imported for the same firewall reason as
// `YFormatterFields` above — keeping the MCP bundle free of `~/` schema deps. Assignability from
// the real `GoalLine` is asserted in trendsChartTransforms.test.ts so this can't silently drift.
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
    yFormatterFields?: YFormatterFields | null
    baseCurrency?: string
    showValuesOnSeries?: boolean
    showCrosshair?: boolean
    showConfidenceIntervals?: boolean
    confidenceLevel?: number
    showMovingAverage?: boolean
    movingAverageIntervals?: number
    showTrendLines?: boolean
}
