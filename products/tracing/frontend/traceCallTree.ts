import type { SpanTreeNode } from '~/queries/schema/schema-general'

import { compareRowKey } from './compareUtils'
import type { FlameTreeNode } from './flameTree'
import { parseTimestampUs } from './spanTree'
import type { Span } from './types'

const ROOT_NAME = '<ROOT>'

function median(sortedValues: number[]): number {
    const mid = Math.floor(sortedValues.length / 2)
    return sortedValues.length % 2 === 1 ? sortedValues[mid] : (sortedValues[mid - 1] + sortedValues[mid]) / 2
}

function nearestRank(sortedValues: number[], quantile: number): number {
    return sortedValues[Math.min(sortedValues.length - 1, Math.ceil(quantile * sortedValues.length) - 1)]
}

// A root span has the all-zero OTel parent id, which the API returns as hex ("0000000000000000"), not "".
// A span that names itself as its parent is a root too, because as its own child no path from a root reaches it.
function parentSpanOf(span: Span, spansById: Map<string, Span>): Span | null {
    if (
        span.is_root_span ||
        !span.parent_span_id ||
        /^0+$/.test(span.parent_span_id) ||
        span.parent_span_id === span.span_id
    ) {
        return null
    }
    return spansById.get(span.parent_span_id) ?? null
}

/** The stats of the spans of one operation that `caller` ran. */
function summarizeCalls(spans: Span[], caller: FlameTreeNode, spansById: Map<string, Span>): SpanTreeNode {
    const sortedDurations = spans.map((span) => span.duration_nano).sort((a, b) => a - b)
    let total = 0
    let errorCount = 0
    let startOffsetTotalNano = 0
    for (const span of spans) {
        total += span.duration_nano
        if (span.status_code === 2) {
            errorCount += 1
        }
        const parent = parentSpanOf(span, spansById)
        if (parent) {
            startOffsetTotalNano += (parseTimestampUs(span.timestamp) - parseTimestampUs(parent.timestamp)) * 1_000
        }
    }
    const count = spans.length
    return {
        parent_service: caller.serviceName,
        parent_name: caller.name,
        service_name: spans[0].service_name,
        name: spans[0].name,
        count,
        total_duration_nano: total,
        avg_duration_nano: total / count,
        // The median, not the nearest rank, so that the flame and the Operations tab show the same p50.
        p50_duration_nano: median(sortedDurations),
        p95_duration_nano: nearestRank(sortedDurations, 0.95),
        p99_duration_nano: nearestRank(sortedDurations, 0.99),
        p999_duration_nano: nearestRank(sortedDurations, 0.999),
        error_count: errorCount,
        avg_start_offset_nano: startOffsetTotalNano / count,
        // A caller node counts its spans, so this divides by the caller spans, not by the one merged caller node.
        calls_per_parent_invocation: caller.node ? count / caller.node.count : null,
    }
}

/**
 * One trace's spans as the tree TraceCompareFlame draws. Like a profiler flame graph, spans merge by their path of
 * operations from the root: an operation that two callers run gets one node under each caller, and each node counts
 * only the calls of that caller.
 */
export function buildTraceCallTree(spans: Span[]): FlameTreeNode {
    const spansById = new Map<string, Span>()
    for (const span of spans) {
        spansById.set(span.span_id, span)
    }

    // Iterate the span_id index, not the input, so that a duplicate span row counts once, like in buildSpanTree.
    const rootSpans: Span[] = []
    const childSpansByParentId = new Map<string, Span[]>()
    for (const span of spansById.values()) {
        const parent = parentSpanOf(span, spansById)
        if (!parent) {
            rootSpans.push(span)
            continue
        }
        const siblings = childSpansByParentId.get(parent.span_id)
        if (siblings) {
            siblings.push(span)
        } else {
            childSpansByParentId.set(parent.span_id, [span])
        }
    }

    const root: FlameTreeNode = { serviceName: '', name: ROOT_NAME, node: null, previousNode: null, children: [] }
    // Iterative so that a deep parent/child chain cannot overflow the call stack. The walk needs no visited set:
    // each span is in one child list only, and no path from a root reaches a span in a parent cycle.
    const pending: { node: FlameTreeNode; childSpans: Span[] }[] = [{ node: root, childSpans: rootSpans }]
    while (pending.length > 0) {
        const { node, childSpans } = pending.pop()!
        const spansByOperation = new Map<string, Span[]>()
        for (const span of childSpans) {
            const key = compareRowKey(span)
            const operationSpans = spansByOperation.get(key)
            if (operationSpans) {
                operationSpans.push(span)
            } else {
                spansByOperation.set(key, [span])
            }
        }
        for (const operationSpans of spansByOperation.values()) {
            const child: FlameTreeNode = {
                serviceName: operationSpans[0].service_name,
                name: operationSpans[0].name,
                node: summarizeCalls(operationSpans, node, spansById),
                previousNode: null,
                children: [],
            }
            node.children.push(child)
            pending.push({
                node: child,
                childSpans: operationSpans.flatMap((span) => childSpansByParentId.get(span.span_id) ?? []),
            })
        }
        // Earlier operations go to the left, like in the compare flame.
        node.children.sort((a, b) => (a.node?.avg_start_offset_nano ?? 0) - (b.node?.avg_start_offset_nano ?? 0))
    }
    return root
}
