import type { MetricInterval } from '@/model/types'

import type { RangeValues } from '../rangePresets'

const HOURLY_FROM = new Set(['dStart', '-1dStart', '-1h', '-24h', '-48h'])
const MONTHLY_FROM = new Set(['-180d', 'yStart', 'all'])
const DAY_MS = 86_400_000

function parseStart(value: string | null): number {
    if (!value) {
        return Number.NaN
    }
    const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
    return day ? new Date(Number(day[1]), Number(day[2]) - 1, Number(day[3])).getTime() : Date.parse(value)
}

/**
 * The web's `getDefaultInterval` (`lib/utils/dateFilters.ts`). The web's minute buckets for the last hour become hours,
 * because the phone has no minute axis.
 */
export function webAnalyticsInterval(values: RangeValues, now: number = Date.now()): MetricInterval {
    if (HOURLY_FROM.has(values.date_from)) {
        return 'hour'
    }
    if (MONTHLY_FROM.has(values.date_from)) {
        return 'month'
    }
    const from = parseStart(values.date_from)
    if (!Number.isFinite(from)) {
        return 'day'
    }
    const toValue = parseStart(values.date_to)
    // Like the web, the span runs from start to start: Nov 1 to Nov 15 is 14 days.
    const days = ((Number.isFinite(toValue) ? toValue : now) - from) / DAY_MS
    if (days >= 60) {
        return 'month'
    }
    if (days >= 14) {
        return 'week'
    }
    return days >= 2 ? 'day' : 'hour'
}
