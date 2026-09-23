import { dayjs } from 'lib/dayjs'

import { TRACE_LOOKUP_WINDOW_HOURS } from './traceLinks'

/**
 * Which ids an exception was matched on, in falling order of confidence. One type for both
 * surfaces, so a badge's answer can open the drawer's tab on the same footing.
 */
export type ErrorScope = 'span' | 'trace' | 'session'

// How far from a span an exception in the same session can sit and still count as related. It
// matches the window the Logs product's Related errors surface uses, so the same session reads
// the same way in both products.
export const SESSION_ERRORS_WINDOW_HOURS = 6

export interface ErrorsWindow {
    date_from: string
    date_to: string
}

// The union of every timestamp's own window, so a set of spans that covers a wide range asks
// about a wide range. Null when no timestamp parses, because there is then no range to ask about.
function errorsWindow(timestamps: (string | null)[], hours: number): ErrorsWindow | null {
    let earliest = Number.POSITIVE_INFINITY
    let latest = Number.NEGATIVE_INFINITY
    for (const timestamp of timestamps) {
        // Guard before dayjs, because dayjs(undefined) reads as the current time.
        if (!timestamp) {
            continue
        }
        const parsed = dayjs(timestamp)
        if (!parsed.isValid()) {
            continue
        }
        const milliseconds = parsed.valueOf()
        if (milliseconds < earliest) {
            earliest = milliseconds
        }
        if (milliseconds > latest) {
            latest = milliseconds
        }
    }
    if (!Number.isFinite(earliest) || !Number.isFinite(latest)) {
        return null
    }
    // The DateRange key names an ErrorTrackingQuery takes, so the drawer's tab passes the result
    // straight through.
    return {
        date_from: dayjs(earliest).subtract(hours, 'hours').toISOString(),
        date_to: dayjs(latest).add(hours, 'hours').toISOString(),
    }
}

export function sessionErrorsWindow(timestamps: (string | null)[]): ErrorsWindow | null {
    return errorsWindow(timestamps, SESSION_ERRORS_WINDOW_HOURS)
}

// An exception that carries a trace id happened inside that trace, so the window only has to cover
// the trace itself. `traceLookupDateRange` is the same window for a single timestamp.
export function traceErrorsWindow(timestamps: (string | null)[]): ErrorsWindow | null {
    return errorsWindow(timestamps, TRACE_LOOKUP_WINDOW_HOURS)
}

/**
 * A trace or span id in the form the events hold it, or null when the row carries none.
 *
 * Spans read their ids back as uppercase hex while the SDKs write them lowercase. An id of all
 * zeros is OpenTelemetry's "no id" sentinel, and it arrives as a string like any other, so a
 * caller that only checks for a value would match every uninstrumented row to it.
 */
export function usableId(value: string | null | undefined): string | null {
    if (!value) {
        return null
    }
    const normalized = value.toLowerCase()
    return /^0+$/.test(normalized) ? null : normalized
}
