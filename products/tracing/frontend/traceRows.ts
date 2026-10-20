import { dayjs } from 'lib/dayjs'

import type { TracingOrderBy, TracingOrderDirection } from './tracingFiltersLogic'
import type { Span } from './types'

// One row per trace. If the root span never arrived (e.g. an upstream service started the trace
// but doesn't export to PostHog), the top loaded span stands in for it.
export function traceRows(spans: Span[], orderBy: TracingOrderBy, orderDirection: TracingOrderDirection): Span[] {
    const roots = spans.filter((s) => s.is_root_span)
    const tracesWithRoot = new Set(roots.map((s) => s.trace_id))
    const orphans = new Map<string, Span[]>()
    for (const span of spans) {
        if (!tracesWithRoot.has(span.trace_id)) {
            const traceSpans = orphans.get(span.trace_id) ?? []
            traceSpans.push(span)
            orphans.set(span.trace_id, traceSpans)
        }
    }
    if (orphans.size === 0) {
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

    // The API sorts root rows first, so put promoted rows back in trace order.
    const key = (s: Span): number =>
        orderBy === 'duration' ? (s.trace_duration ?? s.duration_nano) : dayjs(s.trace_start ?? s.timestamp).valueOf()
    const dir = orderDirection === 'ASC' ? 1 : -1
    return [...roots, ...promoted].sort((a, b) => (key(a) - key(b)) * dir)
}
