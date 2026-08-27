// Wire types for the metrics pipelines API. These mirror the serializers in
// products/metrics/backend/presentation/pipelines_api.py until `hogli
// build:openapi` publishes generated equivalents to swap in.

export type PipelineHealthState = 'healthy' | 'degraded' | 'critical' | 'no_data'
export type PipelineStatFormat = 'rate' | 'bytes' | 'pct' | 'count' | 'duration'

export interface PipelineFilterType {
    key: string
    op?: 'eq' | 'neq' | 'regex' | 'not_regex'
    value: string
    scope?: 'resource' | 'attribute' | 'auto'
}

export interface PipelineThresholdBoundsType {
    lower?: number | null
    upper?: number | null
}

export interface PipelineThresholdsType {
    warn?: PipelineThresholdBoundsType | null
    crit?: PipelineThresholdBoundsType | null
}

export interface PipelineBreakdownType {
    group_by_key: string
    top_n?: number
    scope?: 'resource' | 'attribute' | 'auto'
}

export interface PipelineStatType {
    id: string
    label: string
    format?: PipelineStatFormat
    metric_name: string
    aggregation?: string
    quantile?: number | null
    metric_type?: string | null
    filters?: PipelineFilterType[]
    thresholds?: PipelineThresholdsType | null
    breakdown?: PipelineBreakdownType | null
}

export interface PipelineLinkType {
    label: string
    url: string
}

export interface PipelineNodeType {
    id: string
    name: string
    kind?: string
    stats: PipelineStatType[]
    headline_stat_ids?: string[]
    links?: PipelineLinkType[]
    note?: string
}

export interface PipelineEdgeType {
    source: string
    target: string
    metric_name: string
    aggregation?: string
    quantile?: number | null
    metric_type?: string | null
    filters?: PipelineFilterType[]
    baseline_offset?: string
    hot_multiplier?: number
}

export interface PipelineVariableType {
    key: string
    label: string
    filter_key: string
    options?: string[]
    default?: string | null
}

export interface PipelineConfigType {
    nodes: PipelineNodeType[]
    edges: PipelineEdgeType[]
    variables?: PipelineVariableType[]
}

export interface MetricsPipelineType {
    id: string
    name: string
    description: string
    config: PipelineConfigType
    enabled: boolean
    created_at: string
    created_by: { id: number; email: string; first_name?: string } | null
    updated_at: string | null
}

export interface PipelineBreakdownRowType {
    label: string
    value: number
}

export interface PipelineStatResultType {
    id: string
    label: string
    format: PipelineStatFormat
    value: number | null
    state: PipelineHealthState
    breakdown_rows: PipelineBreakdownRowType[]
    breakdown_others: PipelineBreakdownRowType | null
}

export interface PipelineNodeResultType {
    id: string
    state: PipelineHealthState
    stats: PipelineStatResultType[]
}

export interface PipelinePointType {
    time: string
    value: number | null
}

export interface PipelineEdgeResultType {
    source: string
    target: string
    current_value: number | null
    baseline_value: number | null
    multiplier: number | null
    hot: boolean
    points: PipelinePointType[]
}

export interface PipelineAlertType {
    severity: 'warning' | 'critical'
    node_id: string
    stat_id: string
    message: string
}

export interface PipelineEvaluationType {
    nodes: PipelineNodeResultType[]
    edges: PipelineEdgeResultType[]
    alerts: PipelineAlertType[]
    date_from: string
    date_to: string
}

export function formatStatValue(value: number | null, format: PipelineStatFormat): string {
    if (value === null) {
        return '—'
    }
    switch (format) {
        case 'rate':
            return `${humanNumber(value)}/s`
        case 'bytes':
            return humanBytes(value)
        case 'pct':
            return `${(value * 100).toFixed(value >= 1 ? 0 : 2)}%`
        case 'duration':
            return humanDuration(value)
        default:
            return humanNumber(value)
    }
}

function humanNumber(value: number): string {
    const abs = Math.abs(value)
    if (abs >= 1_000_000) {
        return `${(value / 1_000_000).toFixed(1)}M`
    }
    if (abs >= 1_000) {
        return `${(value / 1_000).toFixed(1)}k`
    }
    return abs >= 100 ? value.toFixed(0) : value.toFixed(abs >= 1 ? 1 : 2)
}

function humanBytes(value: number): string {
    const units = ['B', 'KB', 'MB', 'GB', 'TB']
    let unitIndex = 0
    let scaled = value
    while (scaled >= 1024 && unitIndex < units.length - 1) {
        scaled /= 1024
        unitIndex += 1
    }
    return `${scaled.toFixed(1)} ${units[unitIndex]}/s`
}

function humanDuration(seconds: number): string {
    if (seconds < 1) {
        return `${(seconds * 1000).toFixed(0)}ms`
    }
    return `${seconds.toFixed(2)}s`
}
