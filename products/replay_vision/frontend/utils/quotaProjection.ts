import { dayjs } from 'lib/dayjs'

import type { VisionQuotaApi } from '../generated/api.schemas'

export const QUOTA_WARN_THRESHOLD = 0.85

export type QuotaStatus = 'safe' | 'warning' | 'danger'

export interface QuotaProjection {
    status: QuotaStatus
    capReachDate: dayjs.Dayjs | null
    capReachInPeriod: boolean
    projectedPeriodEndRatio: number
    resetsOn: string | null
    daysRemaining: number
    combinedDailyRate: number
}

const EMPTY: QuotaProjection = {
    status: 'safe',
    capReachDate: null,
    capReachInPeriod: false,
    projectedPeriodEndRatio: 0,
    resetsOn: null,
    daysRemaining: 0,
    combinedDailyRate: 0,
}

/**
 * Project quota usage to period end from the enabled fleet's summed per-scanner estimates.
 * `scannerProjectedMonthlyDelta` adjusts the fleet sum for a scanner being edited:
 * its proposed monthly estimate minus the stored contribution already in the sum.
 */
export function projectQuota(quota: VisionQuotaApi | null, scannerProjectedMonthlyDelta: number = 0): QuotaProjection {
    if (!quota || quota.monthly_quota <= 0) {
        return EMPTY
    }
    const now = dayjs()
    const used = quota.usage_this_month
    const cap = quota.monthly_quota
    const periodStart = quota.period_start ? dayjs(quota.period_start) : null
    const periodEnd = quota.period_end ? dayjs(quota.period_end) : null
    const periodLengthDays = periodStart && periodEnd ? Math.max(periodEnd.diff(periodStart, 'day', true), 1) : 30
    const daysRemaining = periodEnd ? Math.max(periodEnd.diff(now, 'day', true), 0) : 0
    const resetsOn = periodEnd ? periodEnd.format('MMMM D') : null

    const projectedMonthly = Math.max(quota.projected_monthly_observations + scannerProjectedMonthlyDelta, 0)
    const combinedDailyRate = projectedMonthly / periodLengthDays

    const projectedPeriodEndRatio = (used + combinedDailyRate * daysRemaining) / cap
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
        projectedPeriodEndRatio,
        resetsOn,
        daysRemaining,
        combinedDailyRate,
    }
}

/**
 * Disabled-reason / tooltip for scan triggers based on the monthly observation quota.
 * Assumes block-only overage policy; revisit when `usage_based` lands so we don't disable on metered orgs.
 */
export function quotaUx(quota: VisionQuotaApi | null): { disabledReason?: string; tooltip?: string } {
    if (!quota || quota.monthly_quota <= 0) {
        return {}
    }
    const resetsOn = dayjs(quota.period_end).format('MMMM D')
    if (quota.exhausted) {
        return { disabledReason: `Monthly observation quota reached. Resets ${resetsOn}.` }
    }
    if (quota.usage_this_month / quota.monthly_quota >= QUOTA_WARN_THRESHOLD) {
        return {
            tooltip: `${quota.remaining.toLocaleString()} observations left this month (resets ${resetsOn})`,
        }
    }
    return {}
}
