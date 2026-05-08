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
    | 'ActionsBarValue'
    | 'ActionsAreaGraph'
    | 'BoldNumber'
    | 'ActionsPie'
    | 'ActionsTable'
    | 'WorldMap'

export interface TrendsFilter {
    display?: ChartDisplayType
    showLegend?: boolean
    showValuesOnSeries?: boolean
    aggregationAxisFormat?: 'numeric' | 'duration' | 'duration_ms' | 'percentage'
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

export interface TableVisualizerProps {
    results: HogQLResult
}
