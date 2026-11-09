import api from 'lib/api'
import type { TraceLinkParams } from 'lib/components/ViewTraceButton/traceUrl'

import { resolveTraceLookupRange } from './traceLinks'
import type { Span } from './types'

// The trace endpoint pages at 2,000 spans, so this caps a view at 10,000. Bigger traces open in
// Tracing, which pages in on scroll.
const MAX_TRACE_PAGES = 5

export interface TraceSpanPages {
    spans: Span[]
    truncated: boolean
}

export async function loadTraceSpanPages(
    trace: TraceLinkParams,
    breakpoint: () => void,
    keepPaging: () => boolean = () => true
): Promise<TraceSpanPages> {
    const dateRange = resolveTraceLookupRange(trace.ts)
    const seen = new Set<string>()
    const spans: Span[] = []
    let offset: number | undefined = undefined
    try {
        for (let page = 0; page < MAX_TRACE_PAGES; page++) {
            const response = await api.tracing.getTrace(trace.traceId, { dateRange, offset })
            breakpoint()
            // A page that adds no new span means the pages overlap, so paging further only repeats them.
            const fresh = (response.results as Span[]).filter((span) => !seen.has(span.span_id))
            fresh.forEach((span) => seen.add(span.span_id))
            spans.push(...fresh)
            if (!response.hasMore || response.nextOffset == null || fresh.length === 0) {
                return { spans, truncated: false }
            }
            if (!keepPaging()) {
                return { spans, truncated: true }
            }
            offset = response.nextOffset
        }
    } catch (error) {
        // A failure from a load that a newer one replaced must not mark the newer trace as failed.
        breakpoint()
        throw error
    }
    return { spans, truncated: true }
}
