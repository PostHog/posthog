import { dayjs } from 'lib/dayjs'

import type { DateRange } from '~/queries/schema/schema-general'

// Mirrors MAX_WINDOW_START_AGE_DAYS in products/logs/backend/series_bands.py, which rejects older starts.
export const MAX_WINDOW_START_AGE_DAYS = 35
export const WEEK_DAYS = 7

export interface AnomaliesRollingOption {
    label: string
    dateFrom: string
    hours: number
}

export const ANOMALIES_ROLLING_OPTIONS: AnomaliesRollingOption[] = [
    { label: '24 hours', dateFrom: '-24h', hours: 24 },
    { label: '3 days', dateFrom: '-3d', hours: 72 },
    { label: '7 days', dateFrom: '-7d', hours: 168 },
]

const RELATIVE_FROM_REGEX = /^-(\d+)([hd])$/

export interface AnomaliesWindow {
    start: dayjs.Dayjs
    end: dayjs.Dayjs
    rolling: boolean
}

export function resolveAnomaliesWindow(dateRange: DateRange, now: dayjs.Dayjs): AnomaliesWindow | null {
    const end = dateRange.date_to ? dayjs(dateRange.date_to) : now
    if (!end.isValid()) {
        return null
    }
    const cappedEnd = end.isAfter(now) ? now : end
    const relative = dateRange.date_from?.match(RELATIVE_FROM_REGEX)
    const start = relative
        ? cappedEnd.subtract(parseInt(relative[1], 10), relative[2] === 'h' ? 'hour' : 'day')
        : dateRange.date_from
          ? dayjs(dateRange.date_from)
          : cappedEnd.subtract(WEEK_DAYS, 'day')
    if (!start.isValid()) {
        return null
    }
    return { start, end: cappedEnd, rolling: !dateRange.date_to }
}

export function isWindowStartAllowed(start: dayjs.Dayjs, now: dayjs.Dayjs): boolean {
    return !start.isBefore(now.subtract(MAX_WINDOW_START_AGE_DAYS, 'day')) && !start.isAfter(now)
}

export function weekStartingOn(day: dayjs.Dayjs): DateRange {
    const start = day.startOf('day')
    return { date_from: start.toISOString(), date_to: start.add(WEEK_DAYS, 'day').toISOString() }
}

// A step that reaches the present returns to the rolling option, because a fixed window ending at the click goes stale.
export function stepAnomaliesWindow(dateRange: DateRange, direction: -1 | 1, now: dayjs.Dayjs): DateRange | null {
    const window = resolveAnomaliesWindow(dateRange, now)
    if (!window) {
        return null
    }
    if (direction === 1 && window.rolling) {
        return null
    }
    const spanMs = dateRange.date_to ? dayjs(dateRange.date_to).diff(window.start) : window.end.diff(window.start)
    const start = window.start.add(direction * spanMs, 'millisecond')
    const end = start.add(spanMs, 'millisecond')
    if (!end.isBefore(now)) {
        const rolling = ANOMALIES_ROLLING_OPTIONS.find((option) => option.hours * 3600 * 1000 === spanMs)
        return rolling
            ? { date_from: rolling.dateFrom, date_to: null }
            : { date_from: start.toISOString(), date_to: null }
    }
    if (!isWindowStartAllowed(start, now)) {
        return null
    }
    return { date_from: start.toISOString(), date_to: end.toISOString() }
}
