import { dayjs } from 'lib/dayjs'

import type { VisionQuotaApi } from '../generated/api.schemas'
import { billableCredits, formatCreditCount } from './credits'

export const QUOTA_WARN_THRESHOLD = 0.85

export const IMMINENT_CAP_DAYS = 3

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
    resetsOn: string | null
    /** Actual spend as a percentage of the limit; `QuotaMeterBar` rescales past 100 for display. */
    usedPct: number
    /** The slice of `usedPct` covered by non-billable credits, so the meter can shade it separately. */
    usedFreePct: number
    /** Projected additional spend as a percentage of the limit, unclamped. */
    projectedPct: number
}

const EMPTY: QuotaProjection = {
    status: 'safe',
    exhausted: false,
    capReachDate: null,
    resetsOn: null,
    usedPct: 0,
    usedFreePct: 0,
    projectedPct: 0,
}

/** True when the org has a real spend limit to render a meter against; uncapped orgs get spend-only UI. */
export function hasCreditLimit(quota: VisionQuotaApi | null): quota is VisionQuotaApi & { credit_limit: number } {
    // 0 is a real (fully blocking) limit; only null means uncapped.
    return !!quota && quota.credit_limit !== null
}

/**
 * True when spending credits can actually produce a bill, so the `≈ $` conversions mean something.
 * An org whose whole limit is the free allocation can never be charged — it just stops scanning at the cap —
 * so those surfaces speak in credits only. Unknown quota keeps the dollars rather than flickering them away.
 */
export function hasBillableSpend(quota: VisionQuotaApi | null): boolean {
    if (!hasCreditLimit(quota)) {
        return true
    }
    return billableCredits(quota.credit_limit, quota.free_monthly_credits) > 0
}

/**
 * True when the org's whole limit is the free allocation, so it is on the free plan rather than
 * capped by choice. A zero limit is excluded: that is a deliberate spend cap, not a free plan.
 * Drives copy, where "you ran out of free credits" and "you hit your limit" are different messages.
 */
export function isFreeAllocationOnly(quota: VisionQuotaApi | null): boolean {
    if (!hasCreditLimit(quota) || quota.credit_limit <= 0) {
        return false
    }
    return billableCredits(quota.credit_limit, quota.free_monthly_credits) === 0
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

    // `used >= cap` without `exhausted`: a display clamp (startup cap) lowered the limit below spend,
    // so the backend isn't blocking yet. Being over the limit must not read quieter than approaching it.
    const status: QuotaStatus =
        quota.exhausted || capReachInPeriod || used >= cap
            ? 'danger'
            : projectedPeriodEndRatio >= QUOTA_WARN_THRESHOLD
              ? 'warning'
              : 'safe'

    return {
        status,
        exhausted: quota.exhausted,
        capReachDate,
        resetsOn,
        usedPct: (used / cap) * 100,
        usedFreePct: (Math.min(used, quota.free_monthly_credits) / cap) * 100,
        projectedPct: (projectedAdditional / cap) * 100,
    }
}

/** Null unless the limit lands within IMMINENT_CAP_DAYS and scanning hasn't already stopped. */
export function daysUntilCapReached(projection: QuotaProjection): number | null {
    if (!projection.capReachDate || projection.exhausted) {
        return null
    }
    const days = Math.max(projection.capReachDate.diff(dayjs(), 'day', true), 0)
    return days <= IMMINENT_CAP_DAYS ? days : null
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
        return {
            disabledReason: isFreeAllocationOnly(quota)
                ? `You've used all your free Replay vision credits. Resets ${state.resetsOn}.`
                : `Replay vision spend limit reached. Resets ${state.resetsOn}.`,
        }
    }
    return {
        tooltip: `${formatCreditCount(state.quota.remaining ?? 0)} left this billing period (resets ${state.resetsOn})`,
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

/** "You'll hit your limit around Jul 24": null when uncapped, unused, exhausted, or safely within budget. */
export function exhaustionForecast(
    creditsUsed: number,
    creditLimit: number | null,
    periodStart: string,
    periodEnd: string
): string | null {
    if (creditLimit === null || creditsUsed <= 0 || creditsUsed >= creditLimit) {
        return null
    }
    const elapsedMs = Date.now() - dayjs(periodStart).valueOf()
    if (elapsedMs <= 0) {
        return null
    }
    const burnPerMs = creditsUsed / elapsedMs
    const msToLimit = (creditLimit - creditsUsed) / burnPerMs
    const exhaustAt = dayjs(Date.now() + msToLimit)
    if (exhaustAt.isAfter(dayjs(periodEnd))) {
        return null
    }
    return exhaustAt.format('MMM D')
}
