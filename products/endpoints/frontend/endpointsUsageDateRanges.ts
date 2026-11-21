import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'
import { formatDateRange } from 'lib/utils/datetime'

import { DateMappingOption, IntervalType } from '~/types'

export interface EndpointsUsageDateRange {
    /** The relative `dateFrom` the logic and the URL carry, such as `-7d`. */
    key: string
    label: string
    start: (now: dayjs.Dayjs) => dayjs.Dayjs
    defaultInterval: IntervalType
}

export const ENDPOINTS_USAGE_DATE_RANGES: EndpointsUsageDateRange[] = [
    { key: '-24h', label: 'Last 24 hours', start: (now) => now.subtract(24, 'hour'), defaultInterval: 'hour' },
    { key: '-48h', label: 'Last 48 hours', start: (now) => now.subtract(48, 'hour'), defaultInterval: 'hour' },
    { key: '-7d', label: 'Last 7 days', start: (now) => now.subtract(7, 'day'), defaultInterval: 'day' },
    { key: '-14d', label: 'Last 14 days', start: (now) => now.subtract(14, 'day'), defaultInterval: 'day' },
    { key: '-30d', label: 'Last 30 days', start: (now) => now.subtract(30, 'day'), defaultInterval: 'day' },
    { key: '-90d', label: 'Last 90 days', start: (now) => now.subtract(90, 'day'), defaultInterval: 'day' },
    { key: 'yStart', label: 'This year', start: (now) => now.startOf('year'), defaultInterval: 'day' },
]

export const endpointsUsageDateMapping: DateMappingOption[] = ENDPOINTS_USAGE_DATE_RANGES.map((range) => ({
    key: range.label,
    values: [range.key],
    getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(range.start(date), date.endOf('d')),
    defaultInterval: range.defaultInterval,
}))

const MAX_HOURLY_DAYS = 14
const MIN_WEEKLY_DAYS = 14
const MIN_MONTHLY_DAYS = 60

/**
 * The interval the trends charts should use once the date range changes. A range of two days or less is always
 * hourly, because a daily chart of it has one or two points. A longer range keeps the interval in force unless it
 * would draw too many points (hourly past two weeks) or too few (weekly under two weeks, monthly under two months).
 */
export function intervalForDateRange(
    dateFrom: string | null,
    dateTo: string | null,
    interval: IntervalType
): IntervalType {
    const now = dayjs()
    const from = dateStringToDayJs(dateFrom) ?? now.subtract(7, 'day')
    const to = (dateTo ? dateStringToDayJs(dateTo) : null) ?? now
    const days = Math.abs(to.diff(from, 'day', true))

    if (days <= 2) {
        return 'hour'
    }
    if (interval === 'hour' && days > MAX_HOURLY_DAYS) {
        return 'day'
    }
    if (interval === 'week' && days < MIN_WEEKLY_DAYS) {
        return 'day'
    }
    if (interval === 'month' && days < MIN_MONTHLY_DAYS) {
        return 'day'
    }
    return interval
}
