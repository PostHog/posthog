import { dayjs } from 'lib/dayjs'

import type { VisionQuotaApi } from '../generated/api.schemas'

export const QUOTA_WARN_THRESHOLD = 0.8
export const MIN_DAYS_FOR_PROJECTED_DATE = 3

export type QuotaStatus = 'safe' | 'warning' | 'danger'

export interface QuotaProjection {
    status: QuotaStatus
    capReachDate: dayjs.Dayjs | null
    capReachInPeriod: boolean
    projectionConfident: boolean
    projectedPeriodEndRatio: number
    resetsOn: string | null
    daysElapsed: number
    daysRemaining: number
    periodLengthDays: number
    historicalDailyBurn: number
    scannerDailyRate: number
    combinedDailyRate: number
}

interface ProjectQuotaOptions {
    /** Allows tests / future-pinned-time callers to override the clock. Defaults to `dayjs()`. */
    now?: dayjs.Dayjs
    /** Forecasted monthly observations from a candidate scanner. Omit on surfaces with no candidate. */
    scannerProjectedMonthly?: number | null
}

const EMPTY: QuotaProjection = {
    status: 'safe',
    capReachDate: null,
    capReachInPeriod: false,
    projectionConfident: false,
    projectedPeriodEndRatio: 0,
    resetsOn: null,
    daysElapsed: 0,
    daysRemaining: 0,
    periodLengthDays: 0,
    historicalDailyBurn: 0,
    scannerDailyRate: 0,
    combinedDailyRate: 0,
}

export function projectQuota(quota: VisionQuotaApi | null, options: ProjectQuotaOptions = {}): QuotaProjection {
    if (!quota || quota.monthly_quota <= 0) {
        return EMPTY
    }
    const now = options.now ?? dayjs()
    const scannerProjectedMonthly = options.scannerProjectedMonthly ?? null

    const used = quota.usage_this_month
    const cap = quota.monthly_quota
    const periodStart = quota.period_start ? dayjs(quota.period_start) : null
    const periodEnd = quota.period_end ? dayjs(quota.period_end) : null
    const periodLengthDays = periodStart && periodEnd ? Math.max(periodEnd.diff(periodStart, 'day', true), 1) : 30
    const daysElapsed = periodStart ? Math.max(now.diff(periodStart, 'day', true), 0) : 0
    const daysRemaining = periodEnd ? Math.max(periodEnd.diff(now, 'day', true), 0) : 0
    const resetsOn = periodEnd ? periodEnd.format('MMM D') : null
    const projectionConfident = daysElapsed >= MIN_DAYS_FOR_PROJECTED_DATE

    const historicalDailyBurn = daysElapsed > 0 ? used / daysElapsed : 0
    const scannerDailyRate = scannerProjectedMonthly !== null ? scannerProjectedMonthly / periodLengthDays : 0
    const combinedDailyRate = historicalDailyBurn + scannerDailyRate

    const projectedPeriodEndUsage = used + combinedDailyRate * daysRemaining
    const projectedPeriodEndRatio = projectedPeriodEndUsage / cap

    const capReachDate = combinedDailyRate > 0 && used < cap ? now.add((cap - used) / combinedDailyRate, 'day') : null
    const capReachInPeriod = !!(capReachDate && periodEnd && capReachDate.isBefore(periodEnd))

    const status: QuotaStatus =
        quota.exhausted || capReachInPeriod
            ? 'danger'
            : projectedPeriodEndRatio >= QUOTA_WARN_THRESHOLD
              ? 'warning'
              : 'safe'

    return {
        status,
        capReachDate,
        capReachInPeriod,
        projectionConfident,
        projectedPeriodEndRatio,
        resetsOn,
        daysElapsed,
        daysRemaining,
        periodLengthDays,
        historicalDailyBurn,
        scannerDailyRate,
        combinedDailyRate,
    }
}
