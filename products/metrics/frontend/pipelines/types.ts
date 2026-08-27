// Wire types come from the generated client; this module only re-exports them
// under local names and holds the display helpers that have no server side.

import type {
    MetricsPipelineApi,
    PipelineAlertApi,
    PipelineBreakdownRowApi,
    PipelineConfigApi,
    PipelineEdgeApi,
    PipelineEdgeResultApi,
    PipelineEvaluationApi,
    PipelineNodeApi,
    PipelineNodeResultApi,
    PipelinePointApi,
    PipelineStatApi,
    PipelineStatResultApi,
    PipelineThresholdsApi,
    PipelineVariableApi,
} from '../generated/api.schemas'

export type {
    MetricsPipelineApi,
    PipelineAlertApi,
    PipelineBreakdownRowApi,
    PipelineConfigApi,
    PipelineEdgeApi,
    PipelineEdgeResultApi,
    PipelineEvaluationApi,
    PipelineNodeApi,
    PipelineNodeResultApi,
    PipelinePointApi,
    PipelineStatApi,
    PipelineStatResultApi,
    PipelineThresholdsApi,
    PipelineVariableApi,
}

// The serializer keeps these as free-form strings so the OpenAPI spec does not
// grow a component per vocabulary, so the closed sets live here.
export type PipelineHealthState = 'healthy' | 'degraded' | 'critical' | 'no_data'
export type PipelineStatFormat = 'rate' | 'bytes' | 'pct' | 'count' | 'duration'

/** Narrow a server-sent state string, falling back to no_data for anything unrecognised. */
export function toHealthState(state: string): PipelineHealthState {
    return state === 'healthy' || state === 'degraded' || state === 'critical' ? state : 'no_data'
}

export function formatStatValue(value: number | null, format: string): string {
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
    // Scale on the magnitude so a negative delta picks the same unit as its
    // positive twin instead of staying in bytes.
    let scaled = Math.abs(value)
    while (scaled >= 1024 && unitIndex < units.length - 1) {
        scaled /= 1024
        unitIndex += 1
    }
    return `${value < 0 ? '-' : ''}${scaled.toFixed(1)} ${units[unitIndex]}`
}

function humanDuration(seconds: number): string {
    if (seconds < 1) {
        return `${(seconds * 1000).toFixed(0)}ms`
    }
    return `${seconds.toFixed(2)}s`
}
