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
    action?: {
        name?: string
    }
}

export type TrendsResult = TrendsResultItem[]

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

export interface TablePayload extends BasePayload {
    query?: HogQLQuery
    results: HogQLResult
}

// ============================================================================
// Component props
// ============================================================================

export interface TrendsVisualizerProps {
    query: TrendsQuery
    results: TrendsResult
}

export interface FunnelVisualizerProps {
    query: FunnelsQuery
    results: FunnelResult
}

export interface TableVisualizerProps {
    results: HogQLResult
}
