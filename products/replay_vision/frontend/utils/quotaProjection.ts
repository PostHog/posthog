import { dayjs } from 'lib/dayjs'

import type { VisionQuotaApi } from '../generated/api.schemas'

export const QUOTA_WARN_THRESHOLD = 0.85

export type QuotaStatus = 'safe' | 'warning' | 'danger'

export const QUOTA_STATUS_STYLES: Record<QuotaStatus, { bar: string; text: string }> = {
    safe: { bar: 'bg-success', text: 'text-success' },
    warning: { bar: 'bg-warning', text: 'text-warning' },
    danger: { bar: 'bg-danger', text: 'text-danger' },
}

export interface QuotaProjection {
    status: QuotaStatus
    exhausted: boolean
    capReachDate: dayjs.Dayjs | null
    /** Projected period-end usage as a rounded percentage of the cap; exceeds 100 on overshoot. */
    percentLabel: number
    resetsOn: string | null
    /** Actual usage as a percentage of the cap; `QuotaMeterBar` clamps for display. */
    usedPct: number
    /** Projected additional usage as a percentage of the cap, unclamped. */
    projectedPct: number
}

const EMPTY: QuotaProjection = {
    status: 'safe',
    exhausted: false,
    capReachDate: null,
    percentLabel: 0,
    resetsOn: null,
    usedPct: 0,
    projectedPct: 0,
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
    const projectedAdditional = combinedDailyRate * daysRemaining

    const projectedPeriodEndRatio = (used + projectedAdditional) / cap
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
        exhausted: quota.exhausted,
        capReachDate,
        percentLabel: Math.round(projectedPeriodEndRatio * 100),
        resetsOn,
        usedPct: (used / cap) * 100,
        projectedPct: (projectedAdditional / cap) * 100,
    }
}

/** Apportion a projected percentage between this scanner and the rest of the fleet by monthly volume. */
export function splitProjectedPct(
    projectedPct: number,
    thisScannerMonthly: number,
    othersMonthly: number
): { thisScannerPct: number; othersPct: number } {
    const combined = thisScannerMonthly + othersMonthly
    const thisScannerPct = combined > 0 ? (projectedPct * thisScannerMonthly) / combined : 0
    // Exact complement so the two segments always sum to the full projection.
    return { thisScannerPct, othersPct: projectedPct - thisScannerPct }
}

/**
 * Disabled-reason / tooltip for scan triggers based on the monthly observation quota.
 * Assumes block-only overage policy; revisit when `usage_based` lands so we don't disable on metered orgs.
 */
export function quotaUx(quota: VisionQuotaApi | null): { disabledReason?: string; tooltip?: string } {
    const state = quotaBannerState(quota)
    if (!state.kind) {
        return {}
    }
    if (state.kind === 'exhausted') {
        return { disabledReason: `Monthly observation quota reached. Resets ${state.resetsOn}.` }
    }
    return {
        tooltip: `${state.quota.remaining.toLocaleString()} observations left this month (resets ${state.resetsOn})`,
    }
}

/** One shared exhausted/warning classification so the banner, triggers, and tooltips can't drift. */
export function quotaBannerState(
    quota: VisionQuotaApi | null
): { kind: null } | { kind: 'exhausted' | 'warning'; resetsOn: string; quota: VisionQuotaApi } {
    if (!quota || quota.monthly_quota <= 0) {
        return { kind: null }
    }
    const resetsOn = dayjs(quota.period_end).format('MMMM D')
    if (quota.exhausted) {
        return { kind: 'exhausted', resetsOn, quota }
    }
    if (quota.usage_this_month / quota.monthly_quota >= QUOTA_WARN_THRESHOLD) {
        return { kind: 'warning', resetsOn, quota }
    }
    return { kind: null }
}
