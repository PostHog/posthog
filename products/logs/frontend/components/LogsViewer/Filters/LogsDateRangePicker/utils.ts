import { dayjs, dayjsLocalToTimezone } from 'lib/dayjs'

import { DateRange } from '~/queries/schema/schema-general'
import { DateMappingOption } from '~/types'

export const DATE_TIME_FORMAT = 'YYYY-MM-DD HH:mm'

export function getShortLabel(option: DateMappingOption): string {
    return option.key.replace(/^Last /, '')
}

export function formatDateRangeLabel(dateRange: DateRange, timezone: string, dateOptions: DateMappingOption[]): string {
    const { date_from, date_to } = dateRange

    const matchingOption = dateOptions.find(
        (o) => o.values[0] === date_from && (o.values[1] ?? null) === (date_to ?? null)
    )
    if (matchingOption) {
        return matchingOption.key
    }

    const from = date_from ? parseDateExpression(date_from, timezone) : null
    const to = date_to ? parseDateExpression(date_to, timezone) : dayjs().tz(timezone)

    if (from && to) {
        return `${from.format(DATE_TIME_FORMAT)} - ${to.format(DATE_TIME_FORMAT)}`
    }

    if (from) {
        return `${from.format(DATE_TIME_FORMAT)} - now`
    }

    return 'Select date range'
}

const UNIT_MAP: Record<string, 'minute' | 'month' | 'hour' | 'day' | 'week' | 'year' | 'second'> = {
    M: 'minute',
    m: 'month',
    h: 'hour',
    d: 'day',
    w: 'week',
    y: 'year',
    q: 'month', // 'q' represents quarters; it maps to 'month' and is treated as 3 months via a multiplier in parseDateExpression.
    s: 'second',
}

// PostHog convention: M = minutes, m = months (case-sensitive)
const RELATIVE_DATE_REGEX = /^-(\d+)(M|m|h|d|w|y|q|s)$/

export function parseDateExpression(expr: string, timezone: string): dayjs.Dayjs | null {
    const trimmed = expr.trim()

    if (trimmed.toLowerCase() === 'now') {
        return dayjs().tz(timezone)
    }

    const relativeMatch = trimmed.match(RELATIVE_DATE_REGEX)
    if (relativeMatch) {
        const amount = parseInt(relativeMatch[1], 10)
        const unit = relativeMatch[2]
        const multiplier = unit === 'q' ? 3 : 1
        return dayjs()
            .tz(timezone)
            .subtract(amount * multiplier, UNIT_MAP[unit])
    }

    // ISO strings with timezone info (e.g., "2024-01-13T10:00:00.000Z") should be converted to target timezone
    const isIsoWithTimezone = /^\d{4}-\d{2}-\d{2}T.*(Z|[+-]\d{2}:\d{2})$/.test(trimmed)
    if (isIsoWithTimezone) {
        const parsed = dayjs(trimmed).tz(timezone)
        if (parsed.isValid()) {
            return parsed
        }
    }

    // Local time strings (e.g., "2024-01-13 10:00") should be interpreted in target timezone
    const parsed = dayjsLocalToTimezone(trimmed, timezone)
    if (parsed.isValid()) {
        return parsed
    }

    return null
}
