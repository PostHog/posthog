import { dayjs } from 'lib/dayjs'
import { componentsToDayJs, dateStringToComponents } from 'lib/utils/dateFilters'

import type { DateRange } from '~/queries/schema/schema-general'

// Mirrors MAX_WINDOW_START_AGE_DAYS in products/logs/backend/series_bands.py, which rejects older starts.
export const MAX_WINDOW_START_AGE_DAYS = 35
// The backend floors the start by up to one hour bucket and reads its own later clock.
const START_AGE_MARGIN_HOURS = 1
// Hours, not calendar days: a week across a daylight saving change is 169 hours, and the backend refuses it.
const WEEK_HOURS = 7 * 24
// Hours for the same reason: the backend compares elapsed time, and 35 calendar days across a
// daylight saving change is 841 hours, which eats the whole margin.
const MAX_WINDOW_START_AGE_HOURS = MAX_WINDOW_START_AGE_DAYS * 24

export const ANOMALIES_ROLLING_OPTIONS = [
    { label: '24 hours', dateFrom: '-24h' },
    { label: '3 days', dateFrom: '-3d' },
    { label: '7 days', dateFrom: '-7d' },
]

interface AnomaliesWindow {
    start: dayjs.Dayjs
    /** Not capped at now, so a fixed window keeps its full length. */
    end: dayjs.Dayjs
}

// A shared link can carry a relative value in either bound. The backend resolves each bound on its
// own against request time, so a relative bound here must not read the other bound either.
// See _parse_bound in products/logs/backend/series_bands.py.
function parseBound(value: string, now: dayjs.Dayjs): dayjs.Dayjs {
    const relative = dateStringToComponents(value)
    if (!relative) {
        return dayjs(value)
    }
    // The backend resolves a relative value in UTC, where a day is always 24 hours. Browser calendar
    // arithmetic makes "-7d" 169 hours across a fall daylight saving change, and the backend refuses
    // that span. Resolve in UTC, then return to the browser zone, which formatting and the calendar read.
    return componentsToDayJs(relative, now.utc()).local()
}

export function resolveAnomaliesWindow(dateRange: DateRange, now: dayjs.Dayjs): AnomaliesWindow | null {
    const end = dateRange.date_to ? parseBound(dateRange.date_to, now) : now
    // Without a start the window runs back from the charted end, which the backend caps at now.
    const defaultStart = (end.isAfter(now) ? now : end).subtract(WEEK_HOURS, 'hour')
    const start = dateRange.date_from ? parseBound(dateRange.date_from, now) : defaultStart
    return start.isValid() && end.isValid() ? { start, end } : null
}

export function oldestAllowedStart(now: dayjs.Dayjs): dayjs.Dayjs {
    return now.subtract(MAX_WINDOW_START_AGE_HOURS - START_AGE_MARGIN_HOURS, 'hour')
}

/** The local midnights of the first and last calendar day a fixed window covers, for the calendar band. */
export function anomaliesWindowDays(
    dateRange: DateRange,
    now: dayjs.Dayjs
): { firstMs: number; lastMs: number } | null {
    // A rolling window has no end to band, and its start moves with the clock.
    if (!dateRange.date_to) {
        return null
    }
    const window = resolveAnomaliesWindow(dateRange, now)
    if (!window) {
        return null
    }
    return {
        firstMs: window.start.startOf('day').valueOf(),
        // The end bound is exclusive, so the last covered day is the one that holds the final charted moment.
        lastMs: window.end.subtract(1, 'millisecond').startOf('day').valueOf(),
    }
}

export function weekStartingOn(day: dayjs.Dayjs): DateRange {
    const start = day.startOf('day')
    return { date_from: start.toISOString(), date_to: start.add(WEEK_HOURS, 'hour').toISOString() }
}

// A step that reaches the present returns to the rolling option, because a fixed window ending at the click goes stale.
export function stepAnomaliesWindow(dateRange: DateRange, direction: -1 | 1, now: dayjs.Dayjs): DateRange | null {
    const window = resolveAnomaliesWindow(dateRange, now)
    if (!window || (direction === 1 && !window.end.isBefore(now))) {
        return null
    }
    const spanMs = window.end.diff(window.start)
    const start = window.start.add(direction * spanMs, 'millisecond')
    const end = start.add(spanMs, 'millisecond')
    if (!end.isBefore(now)) {
        const rolling = ANOMALIES_ROLLING_OPTIONS.find((option) => {
            const optionWindow = resolveAnomaliesWindow({ date_from: option.dateFrom }, now)
            return optionWindow?.end.diff(optionWindow.start) === spanMs
        })
        return { date_from: rolling?.dateFrom ?? start.toISOString(), date_to: null }
    }
    if (start.isBefore(oldestAllowedStart(now))) {
        return null
    }
    return { date_from: start.toISOString(), date_to: end.toISOString() }
}
