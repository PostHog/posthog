// Visualization type discriminator - tools return this to tell the UI what to render
export type VisualizationType =
    | 'trends'
    | 'funnel'
    | 'table'
    | 'error-list'
    | 'error-trace'

// Base payload that all visualizations share
interface BaseVisualizationPayload {
    _visualization: VisualizationType
    _posthogUrl?: string
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

export interface InsightVizNode {
    kind: 'InsightVizNode'
    source: TrendsQuery | FunnelsQuery
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
    types?: string[]
    hasMore?: boolean
}

// ============================================================================
// Error tracking types
// ============================================================================

export interface ErrorIssue {
    id: string
    name?: string
    description?: string
    status?: 'active' | 'resolved' | 'suppressed'
    occurrences?: number
    users?: number
    sessions?: number
    first_seen?: string
    last_seen?: string
    volume?: number[]
}

export interface StackFrame {
    filename?: string
    abs_path?: string
    function?: string
    lineno?: number
    colno?: number
    context_line?: string
    pre_context?: string[]
    post_context?: string[]
    in_app?: boolean
    lang?: string
}

export interface ExceptionValue {
    type?: string
    value?: string
    stacktrace?: {
        frames?: StackFrame[]
    }
}

export interface ErrorTrace {
    exception?: {
        values?: ExceptionValue[]
    }
    // Flat format (alternative)
    exception_type?: string
    exception_message?: string
    frames?: StackFrame[]
}

// ============================================================================
// Visualization payloads - discriminated union
// ============================================================================

export interface TrendsPayload extends BaseVisualizationPayload {
    _visualization: 'trends'
    query: TrendsQuery | InsightVizNode
    results: TrendsResult
}

export interface FunnelPayload extends BaseVisualizationPayload {
    _visualization: 'funnel'
    query: FunnelsQuery | InsightVizNode
    results: FunnelResult
}

export interface TablePayload extends BaseVisualizationPayload {
    _visualization: 'table'
    query?: HogQLQuery
    results: HogQLResult
}

export interface ErrorListPayload extends BaseVisualizationPayload {
    _visualization: 'error-list'
    issues: ErrorIssue[]
}

export interface ErrorTracePayload extends BaseVisualizationPayload {
    _visualization: 'error-trace'
    issue: ErrorIssue
    traces: ErrorTrace[]
}

// Union of all visualization payloads
export type VisualizationPayload =
    | TrendsPayload
    | FunnelPayload
    | TablePayload
    | ErrorListPayload
    | ErrorTracePayload

// ============================================================================
// Component props
// ============================================================================

export interface TrendsVisualizerProps {
    query: TrendsQuery | InsightVizNode
    results: TrendsResult
}

export interface FunnelVisualizerProps {
    query: FunnelsQuery | InsightVizNode
    results: FunnelResult
}

export interface TableVisualizerProps {
    results: HogQLResult
}

export interface ErrorListVisualizerProps {
    issues: ErrorIssue[]
}

export interface ErrorTraceVisualizerProps {
    issue: ErrorIssue
    traces: ErrorTrace[]
}
