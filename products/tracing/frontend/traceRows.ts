import { dayjs } from 'lib/dayjs'

import type { TracingOrderBy, TracingOrderDirection } from './tracingFiltersLogic'
import type { Span } from './types'

// One row per trace. If the root span never arrived (e.g. an upstream service started the trace
// but doesn't export to PostHog), the top loaded span stands in for it.
export function traceRows(spans: Span[], orderBy: TracingOrderBy, orderDirection: TracingOrderDirection): Span[] {
    const rootByTrace = new Map<string, Span>()
    let hasMultiRootTrace = false
    for (const span of spans) {
        if (!span.is_root_span) {
            continue
        }
        const current = rootByTrace.get(span.trace_id)
        if (current === undefined) {
            rootByTrace.set(span.trace_id, span)
        } else {
            hasMultiRootTrace = true
            if (dayjs(span.timestamp).isBefore(current.timestamp)) {
                rootByTrace.set(span.trace_id, span)
            }
        }
    }
    const roots = [...rootByTrace.values()]

    const orphans = new Map<string, Span[]>()
    for (const span of spans) {
        if (!rootByTrace.has(span.trace_id)) {
            const traceSpans = orphans.get(span.trace_id) ?? []
            traceSpans.push(span)
            orphans.set(span.trace_id, traceSpans)
        }
    }
    if (orphans.size === 0 && !hasMultiRootTrace) {
        return roots
    }

    const promoted = [...orphans.values()].map((traceSpans) => {
        const ids = new Set(traceSpans.map((s) => s.span_id))
        const tops = traceSpans.filter((s) => !ids.has(s.parent_span_id))
        const top = (tops.length > 0 ? tops : traceSpans).reduce((a, b) =>
            dayjs(b.timestamp).isBefore(a.timestamp) ? b : a
        )
        return { ...top, root_missing: true }
    })

    // The API sorts by span, not trace, so restore trace order.
    const key = (s: Span): number =>
        orderBy === 'duration' ? traceRowDuration(s) : dayjs(s.trace_start ?? s.timestamp).valueOf()
    const dir = orderDirection === 'ASC' ? 1 : -1
    return [...roots, ...promoted].sort((a, b) => (key(a) - key(b)) * dir)
}

export function traceRowDuration(span: Span): number {
    return span.trace_duration ?? span.duration_nano
}
