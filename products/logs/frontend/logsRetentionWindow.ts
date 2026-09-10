import { parseDateExpression } from 'lib/components/DateFilter/DateRangePicker'
import { dayjs } from 'lib/dayjs'

import { DateRange } from '~/queries/schema/schema-general'
import { LogsSettings } from '~/types'

// Mirrors DEFAULT_LOGS_RETENTION_DAYS in posthog/models/team/logs_retention.py.
export const DEFAULT_LOGS_RETENTION_DAYS = 14

/** Matches the date format the log rows use, so the two read as the same timeline. */
export const LOGS_RETENTION_DATE_FORMAT = 'YYYY-MM-DD'

export interface LogsRetentionWindow {
    retentionDays: number
    /** Oldest timestamp the environment default still keeps. */
    start: dayjs.Dayjs
    /** True when the whole requested range sits before `start`, so no part of it can return logs. */
    coversWholeRange: boolean
}

export function resolveLogsRetentionDays(logsSettings: LogsSettings | null | undefined): number {
    const days = logsSettings?.retention_days
    return typeof days === 'number' && days > 0 ? days : DEFAULT_LOGS_RETENTION_DAYS
}

export function logsRetentionWindowStart(retentionDays: number, timezone: string): dayjs.Dayjs {
    return dayjs().tz(timezone).subtract(retentionDays, 'days')
}

/**
 * Whether a requested range reaches back past the environment's log retention, which makes an empty
 * result mean "already deleted" rather than "nothing was logged". Retention is stamped at ingest, so
 * raising it never brings older logs back.
 *
 * Returns null when the range sits inside the window. A bound that cannot be parsed also returns
 * null, on either end: the query still runs against whatever the server makes of the bound, so
 * reporting deletion would be a guess. An absent `date_from` is an unbounded start, which always
 * reaches past the window.
 */
export function logsRangeBeyondRetention(
    dateRange: DateRange,
    retentionDays: number,
    timezone: string
): LogsRetentionWindow | null {
    const start = logsRetentionWindowStart(retentionDays, timezone)
    const from = dateRange.date_from ? parseDateExpression(dateRange.date_from, timezone) : null
    if (dateRange.date_from && !from) {
        return null
    }
    if (from && !from.isBefore(start)) {
        return null
    }
    const to = dateRange.date_to ? parseDateExpression(dateRange.date_to, timezone) : dayjs().tz(timezone)
    if (!to) {
        return null
    }
    return { retentionDays, start, coversWholeRange: to.isBefore(start) }
}
