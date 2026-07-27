import { dayjs } from 'lib/dayjs'

import type { VisionQuotaApi } from '../generated/api.schemas'
import { formatCredits } from './credits'

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
    /** Projected period-end spend as a rounded percentage of the limit; exceeds 100 on overshoot. */
    percentLabel: number
    resetsOn: string | null
    /** Actual spend as a percentage of the limit; `QuotaMeterBar` clamps for display. */
    usedPct: number
    /** Projected additional spend as a percentage of the limit, unclamped. */
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

/** True when the org has a real spend limit to render a meter against; uncapped orgs get spend-only UI. */
export function hasCreditLimit(quota: VisionQuotaApi | null): quota is VisionQuotaApi & { credit_limit: number } {
    // 0 is a real (fully blocking) limit; only null means uncapped.
    return !!quota && quota.credit_limit !== null
}

/**
 * Project credit spend to period end from the enabled fleet's summed per-scanner estimates.
 * `scannerProjectedMonthlyCreditsDelta` adjusts the fleet sum for a scanner being edited:
 * its proposed monthly credit estimate minus the stored contribution already in the sum.
 */
export function projectQuota(
    quota: VisionQuotaApi | null,
    scannerProjectedMonthlyCreditsDelta: number = 0
): QuotaProjection {
    if (!hasCreditLimit(quota)) {
        return EMPTY
    }
    const now = dayjs()
    const used = quota.credits_used
    const cap = quota.credit_limit
    if (cap === 0) {
        // A $0 spend limit blocks everything; there is no ratio to project against.
        return {
            ...EMPTY,
            status: 'danger',
            exhausted: quota.exhausted,
            percentLabel: 100,
            usedPct: 100,
            resetsOn: quota.period_end ? dayjs(quota.period_end).format('MMMM D') : null,
        }
    }
    const periodStart = quota.period_start ? dayjs(quota.period_start) : null
    const periodEnd = quota.period_end ? dayjs(quota.period_end) : null
    const periodLengthDays = periodStart && periodEnd ? Math.max(periodEnd.diff(periodStart, 'day', true), 1) : 30
    const daysRemaining = periodEnd ? Math.max(periodEnd.diff(now, 'day', true), 0) : 0
    const resetsOn = periodEnd ? periodEnd.format('MMMM D') : null

    const projectedMonthly = Math.max(quota.projected_monthly_credits + scannerProjectedMonthlyCreditsDelta, 0)
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

/** Apportion a projected percentage between this scanner and the rest of the fleet by monthly credit volume. */
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
 * Disabled-reason / tooltip for scan triggers based on the monthly credit limit.
 * Assumes block-only overage policy; revisit when `usage_based` lands so we don't disable on metered orgs.
 */
export function quotaUx(quota: VisionQuotaApi | null): { disabledReason?: string; tooltip?: string } {
    const state = quotaBannerState(quota)
    if (!state.kind) {
        return {}
    }
    if (state.kind === 'exhausted') {
        return { disabledReason: `Monthly Replay vision spend limit reached. Resets ${state.resetsOn}.` }
    }
    return {
        tooltip: `${formatCredits(state.quota.remaining ?? 0)} left this month (resets ${state.resetsOn})`,
    }
}

/** One shared exhausted/warning classification so the banner, triggers, and tooltips can't drift. */
export function quotaBannerState(
    quota: VisionQuotaApi | null
): { kind: null } | { kind: 'exhausted' | 'warning'; resetsOn: string; quota: VisionQuotaApi } {
    if (!hasCreditLimit(quota)) {
        return { kind: null }
    }
    const resetsOn = dayjs(quota.period_end).format('MMMM D')
    if (quota.exhausted) {
        return { kind: 'exhausted', resetsOn, quota }
    }
    if (quota.credits_used / quota.credit_limit >= QUOTA_WARN_THRESHOLD) {
        return { kind: 'warning', resetsOn, quota }
    }
    return { kind: null }
}
