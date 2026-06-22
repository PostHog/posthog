// Canonical trace URLs (JON-33). The URL is the atomic, shareable form of a trace view:
// `/tracing?trace=<hex>` opens the drawer, `&span=<hex>` anchors a span, `&ts=<iso>` carries the
// root timestamp so a cold load can bound the ClickHouse lookup (the table is time-keyed and OTel
// trace ids embed no timestamp — an unhinted id lookup would scan the whole retention window).

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

export interface TraceLinkParams {
    traceId: string
    spanId?: string | null
    /** ISO timestamp of (any span of) the trace, used to bound the cold-load query. */
    ts?: string | null
}

/** Path + query for a trace view, relative to the app root. */
export function traceUrl({ traceId, spanId, ts }: TraceLinkParams): string {
    const params = new URLSearchParams({ trace: traceId })
    if (spanId) {
        params.set('span', spanId)
    }
    if (ts) {
        params.set('ts', ts)
    }
    return `${urls.tracing()}?${params.toString()}`
}

/** Absolute, shareable URL for a trace view. */
export function absoluteTraceUrl(params: TraceLinkParams): string {
    return urls.absolute(traceUrl(params))
}

/** The window a `ts`-hinted cold load queries: ±1h is generous for any single trace's spans. */
export function traceLookupDateRange(ts: string): { date_from: string; date_to: string } {
    return {
        date_from: dayjs(ts).subtract(1, 'hour').toISOString(),
        date_to: dayjs(ts).add(1, 'hour').toISOString(),
    }
}
