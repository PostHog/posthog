import { compareRowKey } from './compareUtils'
import { childSpansByParentId, parseTimestampUs } from './spanTree'
import type { Span } from './types'

export interface TraceOperation {
    /** compareRowKey(span): the row identity the span tree highlight matches on. */
    key: string
    service_name: string
    name: string
    count: number
    /** The time the operation's spans spend outside their loaded child spans. See selfTimeNanoBySpan. */
    self_time_nano: number
    /** Sum of span durations, so a span and the spans nested in it both count. */
    total_duration_nano: number
    avg_duration_nano: number
    p50_duration_nano: number
    /** self_time_nano / the self time of every span summarized, so the shares add up to 1. 0 when that sum is 0. */
    share: number
}

export interface TraceOperationsSummary {
    operations: TraceOperation[]
    spanCount: number
}

interface OperationAccumulator {
    service_name: string
    name: string
    durations: number[]
    total: number
    selfTime: number
}

function median(sortedValues: number[]): number {
    const mid = Math.floor(sortedValues.length / 2)
    return sortedValues.length % 2 === 1 ? sortedValues[mid] : (sortedValues[mid - 1] + sortedValues[mid]) / 2
}

/**
 * Each span's self time in nanoseconds: its duration minus the union of its loaded child spans' intervals. A child
 * interval is clipped to the span first, because a child can start before its parent or end after it, such as an
 * async job the span only enqueued. Children that overlap count once. A child that is not loaded counts as self time.
 * Keyed by span object, so two spans that share an id in malformed data each get their own value.
 */
export function selfTimeNanoBySpan(spans: Span[]): Map<Span, number> {
    const childrenByParentId = childSpansByParentId(spans)
    const selfTimes = new Map<Span, number>()
    for (const span of spans) {
        const startUs = parseTimestampUs(span.timestamp)
        const endUs = startUs + span.duration_nano / 1_000
        const intervals: [number, number][] = []
        for (const child of childrenByParentId.get(span.span_id) ?? []) {
            const childStartUs = parseTimestampUs(child.timestamp)
            const clippedStartUs = Math.max(childStartUs, startUs)
            const clippedEndUs = Math.min(childStartUs + child.duration_nano / 1_000, endUs)
            if (clippedEndUs > clippedStartUs) {
                intervals.push([clippedStartUs, clippedEndUs])
            }
        }
        intervals.sort((a, b) => a[0] - b[0])
        // Sorted by start, everything from an interval's start up to the furthest end so far is already covered,
        // so each interval adds only the part past that end.
        let coveredUs = 0
        let coveredUntilUs = -Infinity
        for (const [intervalStartUs, intervalEndUs] of intervals) {
            const newFromUs = Math.max(intervalStartUs, coveredUntilUs)
            if (intervalEndUs > newFromUs) {
                coveredUs += intervalEndUs - newFromUs
                coveredUntilUs = intervalEndUs
            }
        }
        // Rounded to whole nanoseconds, and floored at 0, so float error in the microsecond math does not show.
        selfTimes.set(span, Math.max(0, Math.round(span.duration_nano - coveredUs * 1_000)))
    }
    return selfTimes
}

function compareOperations(a: TraceOperation, b: TraceOperation): number {
    if (a.self_time_nano !== b.self_time_nano) {
        return b.self_time_nano - a.self_time_nano
    }
    if (a.count !== b.count) {
        return b.count - a.count
    }
    // Code unit order, not localeCompare, so that the row order does not change with the viewer's locale.
    return a.key < b.key ? -1 : a.key > b.key ? 1 : 0
}

/**
 * The spans grouped by operation. Self time measures where the time goes, because it counts each moment once: the
 * shares add up to 1 over the spans passed in, whether that is the whole trace or one span's subtree.
 */
export function summarizeTraceOperations(spans: Span[]): TraceOperationsSummary {
    const selfTimes = selfTimeNanoBySpan(spans)
    const groups = new Map<string, OperationAccumulator>()
    let selfTimeSum = 0
    for (const span of spans) {
        const key = compareRowKey(span)
        let group = groups.get(key)
        if (!group) {
            group = { service_name: span.service_name, name: span.name, durations: [], total: 0, selfTime: 0 }
            groups.set(key, group)
        }
        const selfTime = selfTimes.get(span) ?? 0
        group.durations.push(span.duration_nano)
        group.total += span.duration_nano
        group.selfTime += selfTime
        selfTimeSum += selfTime
    }

    const operations: TraceOperation[] = Array.from(groups, ([key, group]) => ({
        key,
        service_name: group.service_name,
        name: group.name,
        count: group.durations.length,
        self_time_nano: group.selfTime,
        total_duration_nano: group.total,
        avg_duration_nano: group.total / group.durations.length,
        p50_duration_nano: median(group.durations.sort((a, b) => a - b)),
        share: selfTimeSum > 0 ? group.selfTime / selfTimeSum : 0,
    }))
    operations.sort(compareOperations)

    return { operations, spanCount: spans.length }
}
