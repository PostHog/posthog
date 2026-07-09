import type { YAxisFormat } from '@posthog/quill-charts'

import type { AnalyticsMetadata } from '../types'

// Base payload that all tool results share
interface BasePayload {
    _posthogUrl?: string
    /** Analytics metadata injected by MCP server for user tracking */
    _analytics?: AnalyticsMetadata
}

// ============================================================================
// Query-based visualizations
// ============================================================================

export type ChartDisplayType =
    | 'ActionsLineGraph'
    | 'ActionsLineGraphCumulative'
    | 'ActionsBar'
    | 'ActionsStackedBar'
    | 'ActionsUnstackedBar'
    | 'ActionsBarValue'
    | 'ActionsAreaGraph'
    | 'BoldNumber'
    | 'ActionsPie'
    | 'ActionsTable'
    | 'WorldMap'
    | 'SlopeGraph'

export interface TrendsFilter {
    display?: ChartDisplayType
    showLegend?: boolean
    showValuesOnSeries?: boolean
    showTrendLines?: boolean
    showMovingAverage?: boolean
    movingAverageIntervals?: number
    showConfidenceIntervals?: boolean
    confidenceLevel?: number
    showPercentStackView?: boolean
    aggregationAxisFormat?: YAxisFormat
    aggregationAxisPrefix?: string
    aggregationAxisPostfix?: string
    decimalPlaces?: number
    minDecimalPlaces?: number
}

export interface TrendsQuery {
    kind: 'TrendsQuery'
    trendsFilter?: TrendsFilter
    series?: Array<{
        event?: string
        name?: string
        custom_name?: string
    }>
}

export interface FunnelsQuery {
    kind: 'FunnelsQuery'
    series?: Array<{
        event?: string
        name?: string
        custom_name?: string
    }>
}

export type LifecycleStatus = 'new' | 'returning' | 'resurrecting' | 'dormant'

export interface LifecycleQuery {
    kind: 'LifecycleQuery'
    series?: Array<{
        event?: string
        name?: string
        custom_name?: string
    }>
    lifecycleFilter?: {
        toggledLifecycles?: LifecycleStatus[]
        showLegend?: boolean
        showValuesOnSeries?: boolean
        stacked?: boolean
    }
}

export interface StickinessQuery {
    kind: 'StickinessQuery'
    /** Interval unit the X-axis counts (`day`, `week`, …) — labels the buckets ("N days"). */
    interval?: string
    series?: Array<{
        event?: string
        name?: string
        custom_name?: string
    }>
    stickinessFilter?: {
        display?: string
        showValuesOnSeries?: boolean
    }
}

export interface HogQLQuery {
    kind: 'HogQLQuery'
    query: string
}

export interface TrendsResultItem {
    label?: string
    labels?: string[]
    data?: number[]
    days?: string[]
    count?: number
    aggregated_value?: number
    /** Slope graph only: the last bucket is the current, still-accumulating period (set by the
     * backend SlopeGraphTrendsQueryRunner) so the slope dashes the provisional end like the insight. */
    incomplete_end?: boolean
    action?: {
        name?: string
    }
}

export type TrendsResult = TrendsResultItem[]

export interface LifecycleResultItem extends TrendsResultItem {
    /**
     * Lifecycle bucket the series belongs to. Counts for `dormant` come back negated
     * from the backend so the chart can render them below zero.
     */
    status?: LifecycleStatus
}

export type LifecycleResult = LifecycleResultItem[]

/**
 * Stickiness rows share the trends shape, but `count` (the total distinct users for the series)
 * is always present and is the denominator for the percentage-of-users Y-axis the chart renders.
 */
export interface StickinessResultItem extends TrendsResultItem {
    count: number
}

export type StickinessResult = StickinessResultItem[]

export interface FunnelStep {
    name?: string
    custom_name?: string
    action_id?: string
    count?: number
    order?: number
    type?: string
    breakdown_value?: string | number
    converted_people_url?: string
    dropped_people_url?: string
    average_conversion_time?: number
}

export type FunnelResult = FunnelStep[] | FunnelStep[][]

export interface HogQLResult {
    columns?: string[]
    results?: unknown[][]
}

export type RetentionAggregationType = 'count' | 'sum' | 'avg'
export type RetentionReference = 'total' | 'previous'
export type RetentionPeriod = 'Hour' | 'Day' | 'Week' | 'Month'

export interface RetentionFilter {
    aggregationType?: RetentionAggregationType | null
    period?: RetentionPeriod | null
    retentionReference?: RetentionReference | null
    showTrendLines?: boolean | null
    totalIntervals?: number | null
}

export interface RetentionQuery {
    kind: 'RetentionQuery'
    retentionFilter?: RetentionFilter
}

export interface RetentionValueItem {
    count: number
    aggregation_value?: number | null
}

export interface RetentionResultItem {
    date: string
    label: string
    breakdown_value?: string | number | null
    values: RetentionValueItem[]
}

export type RetentionResult = RetentionResultItem[]

export interface PathsQuery {
    kind: 'PathsQuery'
    pathsFilter?: {
        includeEventTypes?: string[]
        startPoint?: string
        endPoint?: string
    }
}

/**
 * A single edge in a paths result. `source`/`target` are node keys of the form
 * `<stepIndex>_<value>` (e.g. `2_https://example.com/pricing`); `value` is the user
 * count on the edge; `average_conversion_time` is in milliseconds.
 */
export interface PathsResultItem {
    source: string
    target: string
    value: number
    average_conversion_time?: number
}

export type PathsResult = PathsResultItem[]

// ============================================================================
// Tool result payloads
// The visualization type is inferred from the data structure, not a discriminator
// ============================================================================

export interface TrendsPayload extends BasePayload {
    query: TrendsQuery
    results: TrendsResult
}

export interface FunnelPayload extends BasePayload {
    query: FunnelsQuery
    results: FunnelResult
}

export interface LifecyclePayload extends BasePayload {
    query: LifecycleQuery
    results: LifecycleResult
}

export interface TablePayload extends BasePayload {
    query?: HogQLQuery
    results: HogQLResult
}

export interface RetentionPayload extends BasePayload {
    query: RetentionQuery
    results: RetentionResult
}

// ============================================================================
// Component props
// ============================================================================

export interface TrendsVisualizerProps {
    query: TrendsQuery | undefined
    results: TrendsResult
}

export interface FunnelVisualizerProps {
    query: FunnelsQuery
    results: FunnelResult
}

export interface LifecycleVisualizerProps {
    query: LifecycleQuery | undefined
    results: LifecycleResult
}

export interface StickinessVisualizerProps {
    query: StickinessQuery | undefined
    results: StickinessResult
}

export interface TableVisualizerProps {
    results: HogQLResult
}

export interface RetentionVisualizerProps {
    query: RetentionQuery | undefined
    results: RetentionResult
}

export interface PathsVisualizerProps {
    results: PathsResult
}
