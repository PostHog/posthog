import type { Accent } from '@/model/types'

export type ChartKind = 'line' | 'bar'

export type ChartInterval = 'hour' | 'day' | 'week' | 'month'

/**
 * `compact`: a pin in a list, 96pt high, no y labels, first and last x labels.
 * `inline`: a card in a scrolling screen. `fullscreen`: the chart owns the screen, so drags scrub in any direction.
 */
export type ChartVariant = 'compact' | 'inline' | 'fullscreen'

/** Where a chart sits, for the `mobile_chart_*` events. */
export type ChartTrackingContext = 'pin' | 'view' | 'fullscreen'

/** `at` is the bucket start in epoch milliseconds, a plain number that worklets can read. `value` NaN = gap. */
export interface ChartPoint {
    at: number
    value: number
}

export type ChartSeriesStyle = 'solid' | 'dotted'

/**
 * One line, or one set of bars. Every series of a chart has the same number of points, and `points[i]` of every
 * series is bucket `i`.
 */
export interface ChartSeries {
    /** Unique within the chart. The legend and the tooltip key on it. */
    key: string
    /** Series name, with the breakdown value when there is one. */
    label: string
    /** Use `seriesColor(index)` for the web's palette. A `compareOf` series always draws gray. */
    color: string
    points: ChartPoint[]
    /** Defaults to `dotted` for a `compareOf` series and `solid` otherwise. */
    style?: ChartSeriesStyle
    /**
     * The key of the series this one is the previous period of. Its `points[i].at` holds the previous period's
     * date for bucket `i`, so the tooltip can say "Previous: 1,071 (Sep 30)".
     */
    compareOf?: string
    /** The first bucket that is still in progress. The segment into it is dashed, and its tooltip says so. */
    incompleteFrom?: number
}

/** One series' value at the tooltip's bucket. */
export interface ChartTooltipRow {
    key: string
    label: string
    color: string
    value: number
    /** The previous period at the same bucket, when the chart has a compare series for this one. */
    previous?: { value: number; at: number }
}

/** What a tap on the pinned tooltip hands to `onPressTooltip`, for the Point sheet. */
export interface ChartTooltipPoint {
    index: number
    /** Start of the bucket, epoch milliseconds. */
    at: number
    interval: ChartInterval
    /** Every visible current series with a value at this bucket, highest first. Not cut to the tooltip's four. */
    rows: ChartTooltipRow[]
    incomplete: boolean
}

/** A canvas mount budget slot. `index` is the item's position in its list, so the nearest items mount first. */
export interface ChartCanvasSlot {
    key: string
    index: number
}

interface MetricChartBaseProps {
    kind: ChartKind
    interval: ChartInterval
    /** The chart's name, for the accessibility summary. With `points`, also the tooltip row label. */
    label: string
    formatValue: (value: number) => string
    /** Defaults to `inline`. */
    variant?: ChartVariant
    /** Defaults to 96 for `compact` and 144, the web chart's `h-36`, otherwise. */
    height?: number
    /** Series keys the legend hides. The y axis rescales to the rest. */
    hiddenKeys?: readonly string[]
    /** When the data was computed, epoch milliseconds. The in-progress note says "Data until 14:32". */
    dataUntil?: number
    /**
     * Called with the point under the finger each time it changes, and with `null` when the finger lifts (a tap
     * reports its point, then `null`) or the data changes. The chart keeps showing the last selection after release.
     * With several series, the point is the first visible series' value.
     */
    onSelect?: (point: ChartPoint | null) => void
    /** A tap on the pinned tooltip. Without it the tooltip has no chevron and does not take touches. */
    onPressTooltip?: (point: ChartTooltipPoint) => void
    /** Pairs the chart with its `ChartLegend` inside a `ChartSelectionProvider`. Defaults to a generated id. */
    selectionId?: string
    /** Sends the `mobile_chart_*` events with this context. Without it the chart sends none. */
    trackingContext?: ChartTrackingContext
    /** Inside a `ChartCanvasBudget`, the chart mounts its canvas only when this slot is granted. */
    canvasSlot?: ChartCanvasSlot
    /** Replaces the default accessibility summary, for example to name the date range. */
    accessibilitySummary?: string
    /** Extra VoiceOver and TalkBack actions, such as "About this chart". */
    accessibilityActions?: readonly ChartAccessibilityAction[]
    /** The budget placeholder gets `${testID}-placeholder`. The tooltip is always `chart-tooltip`. */
    testID?: string
}

export interface ChartAccessibilityAction {
    name: string
    label: string
    onAction: () => void
}

/** One series in the accent color, as the report charts draw it. */
export interface SingleSeriesChartProps extends MetricChartBaseProps {
    points: ChartPoint[]
    accent: Accent
    series?: undefined
}

export interface MultiSeriesChartProps extends MetricChartBaseProps {
    series: ChartSeries[]
    points?: undefined
    accent?: undefined
}

export type MetricChartProps = SingleSeriesChartProps | MultiSeriesChartProps
