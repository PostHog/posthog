import { dayjs } from 'lib/dayjs'

// How far from a span an exception in the same session can sit and still count as related. It
// matches the window the Logs product's Related errors surface uses, so the same session reads
// the same way in both products.
export const SESSION_ERRORS_WINDOW_HOURS = 6

export interface SessionErrorsWindow {
    date_from: string
    date_to: string
}

// The union of every timestamp's own window, so a set of spans that covers a wide range asks
// about a wide range. Null when no timestamp parses, because there is then no range to ask about.
export function sessionErrorsWindow(timestamps: (string | null)[]): SessionErrorsWindow | null {
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
        date_from: dayjs(earliest).subtract(SESSION_ERRORS_WINDOW_HOURS, 'hours').toISOString(),
        date_to: dayjs(latest).add(SESSION_ERRORS_WINDOW_HOURS, 'hours').toISOString(),
    }
}
