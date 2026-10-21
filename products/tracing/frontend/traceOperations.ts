import { compareRowKey } from './compareUtils'
import { parseTimestampUs } from './spanTree'
import type { Span } from './types'

export interface TraceOperation {
    /** compareRowKey(span): the row identity the span tree highlight matches on. */
    key: string
    service_name: string
    name: string
    count: number
    total_duration_nano: number
    avg_duration_nano: number
    p50_duration_nano: number
    /** total_duration_nano / traceDurationNano. Above 1 when nested spans overlap. 0 when the trace duration is 0. */
    share: number
}

export interface TraceOperationsSummary {
    operations: TraceOperation[]
    /** Earliest span start to latest span end, like the span tree timeline. 0 for no spans. */
    traceDurationNano: number
    spanCount: number
}

interface OperationAccumulator {
    service_name: string
    name: string
    durations: number[]
    total: number
}

function median(sortedValues: number[]): number {
    const mid = Math.floor(sortedValues.length / 2)
    return sortedValues.length % 2 === 1 ? sortedValues[mid] : (sortedValues[mid - 1] + sortedValues[mid]) / 2
}

function compareOperations(a: TraceOperation, b: TraceOperation): number {
    if (a.total_duration_nano !== b.total_duration_nano) {
        return b.total_duration_nano - a.total_duration_nano
    }
    if (a.count !== b.count) {
        return b.count - a.count
    }
    // Code unit order, not localeCompare, so that the row order does not change with the viewer's locale.
    return a.key < b.key ? -1 : a.key > b.key ? 1 : 0
}

export function summarizeTraceOperations(spans: Span[]): TraceOperationsSummary {
    if (spans.length === 0) {
        return { operations: [], traceDurationNano: 0, spanCount: 0 }
    }

    const groups = new Map<string, OperationAccumulator>()
    // A loop, not Math.min(...spread), because a large trace can exceed the engine's argument limit.
    let traceStartUs = Infinity
    let traceEndUs = -Infinity
    for (const span of spans) {
        const startUs = parseTimestampUs(span.timestamp)
        traceStartUs = Math.min(traceStartUs, startUs)
        traceEndUs = Math.max(traceEndUs, startUs + span.duration_nano / 1_000)

        const key = compareRowKey(span)
        let group = groups.get(key)
        if (!group) {
            group = { service_name: span.service_name, name: span.name, durations: [], total: 0 }
            groups.set(key, group)
        }
        group.durations.push(span.duration_nano)
        group.total += span.duration_nano
    }

    const traceDurationNano = (traceEndUs - traceStartUs) * 1_000
    const operations: TraceOperation[] = Array.from(groups, ([key, group]) => ({
        key,
        service_name: group.service_name,
        name: group.name,
        count: group.durations.length,
        total_duration_nano: group.total,
        avg_duration_nano: group.total / group.durations.length,
        p50_duration_nano: median(group.durations.sort((a, b) => a - b)),
        share: traceDurationNano > 0 ? group.total / traceDurationNano : 0,
    }))
    operations.sort(compareOperations)

    return { operations, traceDurationNano, spanCount: spans.length }
}
