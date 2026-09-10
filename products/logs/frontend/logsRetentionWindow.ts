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
 * This reads the environment default only. A retention rule can set a shorter or a longer tier for
 * the logs its filters match, so a range inside this window can still miss logs that a shorter rule
 * deleted. The explorer does not load rules, and a rule applies only to the logs it matches, so the
 * copy names rules as a possible cause and never says one caused the result.
 *
 * Returns null when the range sits inside the window. It also returns null when a bound cannot be
 * resolved here, because the server decides that bound and reporting deletion would then be a
 * guess: an expression this parser does not read, on either end, or an absent `date_from`, for
 * which the query runner applies a default start shorter than the shortest retention tier. An
 * absent `date_to` means now.
 */
export function logsRangeBeyondRetention(
    dateRange: DateRange,
    retentionDays: number,
    timezone: string
): LogsRetentionWindow | null {
    const start = logsRetentionWindowStart(retentionDays, timezone)
    const from = dateRange.date_from ? parseDateExpression(dateRange.date_from, timezone) : null
    if (!from || !from.isBefore(start)) {
        return null
    }
    const to = dateRange.date_to ? parseDateExpression(dateRange.date_to, timezone) : dayjs().tz(timezone)
    if (!to) {
        return null
    }
    return { retentionDays, start, coversWholeRange: to.isBefore(start) }
}
