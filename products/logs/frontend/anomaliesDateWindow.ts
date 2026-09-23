import { dayjs } from 'lib/dayjs'
import { componentsToDayJs, dateStringToComponents } from 'lib/utils/dateFilters'

import type { DateRange } from '~/queries/schema/schema-general'

// Mirrors MAX_WINDOW_START_AGE_DAYS in products/logs/backend/series_bands.py, which rejects older starts.
export const MAX_WINDOW_START_AGE_DAYS = 35
// The backend floors the start by up to one hour bucket and reads its own later clock.
const START_AGE_MARGIN_HOURS = 1
// Hours, not calendar days: a week across a daylight saving change is 169 hours, and the backend refuses it.
const WEEK_HOURS = 7 * 24

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

export function resolveAnomaliesWindow(dateRange: DateRange, now: dayjs.Dayjs): AnomaliesWindow | null {
    const end = dateRange.date_to ? dayjs(dateRange.date_to) : now
    const anchor = end.isAfter(now) ? now : end
    const relative = dateStringToComponents(dateRange.date_from ?? null)
    let start: dayjs.Dayjs
    if (relative) {
        start = componentsToDayJs(relative, anchor)
    } else if (dateRange.date_from) {
        start = dayjs(dateRange.date_from)
    } else {
        start = anchor.subtract(WEEK_HOURS, 'hour')
    }
    return start.isValid() && end.isValid() ? { start, end } : null
}

export function oldestAllowedStart(now: dayjs.Dayjs): dayjs.Dayjs {
    return now.subtract(MAX_WINDOW_START_AGE_DAYS, 'day').add(START_AGE_MARGIN_HOURS, 'hour')
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
