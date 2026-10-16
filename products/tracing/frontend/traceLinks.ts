import { combineUrl } from 'kea-router'

import { type TraceLinkParams, traceUrl } from 'lib/components/ViewTraceButton/traceUrl'
import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import type { DateRange } from '~/queries/schema/schema-general'

/** Absolute, shareable URL for a trace view. */
export function absoluteTraceUrl(params: TraceLinkParams): string {
    return urls.absolute(traceUrl(params))
}

/**
 * Spans for one service over a window — the pivot other products offer when they know a service
 * and a time range but no trace id. The service goes in as a list because `tracingSceneLogic`
 * reads it back through `parseTagsFilter`, which splits a bare string on commas.
 */
export function tracingUrlForService(serviceName: string, { dateRange }: { dateRange?: DateRange } = {}): string {
    return combineUrl(urls.tracing(), {
        serviceNames: [serviceName],
        ...(dateRange ? { dateRange: JSON.stringify(dateRange) } : {}),
    }).url
}

/** The product's docs, linked from the empty states and from surfaces that need instrumenting. */
export const TRACING_DOCS_URL = 'https://posthog.com/docs/tracing'

/** The window a `ts`-hinted cold load queries: ±1h is generous for any single trace's spans. */
export const TRACE_LOOKUP_WINDOW_HOURS = 1

export function traceLookupDateRange(ts: string): { date_from: string; date_to: string } {
    return {
        date_from: dayjs(ts).subtract(TRACE_LOOKUP_WINDOW_HOURS, 'hour').toISOString(),
        date_to: dayjs(ts).add(TRACE_LOOKUP_WINDOW_HOURS, 'hour').toISOString(),
    }
}
