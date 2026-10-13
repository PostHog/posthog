import { dayjs } from 'lib/dayjs'

import type { VisionQuotaApi } from '../generated/api.schemas'
import { billableCredits, formatCreditCount } from './credits'

export const QUOTA_WARN_THRESHOLD = 0.85

export const IMMINENT_CAP_DAYS = 3

/** Scanner estimates are a rate per 30 days (backend `ESTIMATE_WINDOW_DAYS`), not per billing period. */
export const ESTIMATE_MONTH_DAYS = 30

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

export interface ProjectionInputs {
    /** Fleet rate in credits per 30 days; defaults to the quota's stored `scanners_monthly_credits`. */
    monthlyRateCredits?: number
    /** Charged once (backfills), so they count toward the cap-reach date but not the rate. */
    oneOffCredits?: number
}

/** Credits the period ends on: spend so far, the rate pro-rated over the days left, and the one-offs. Unclamped. */
export function projectDemandCredits(quota: VisionQuotaApi, inputs: ProjectionInputs = {}): number {
    const daysRemaining = Math.max(dayjs.utc(quota.period_end).diff(dayjs(), 'day', true), 0)
    const rate = Math.max(inputs.monthlyRateCredits ?? quota.scanners_monthly_credits, 0) / ESTIMATE_MONTH_DAYS
    return quota.credits_used + rate * daysRemaining + Math.max(inputs.oneOffCredits ?? 0, 0)
}

/** Project credit spend to period end from a fleet rate and the one-offs already committed. */
export function projectQuota(quota: VisionQuotaApi | null, inputs: ProjectionInputs = {}): QuotaProjection {
    if (!hasCreditLimit(quota)) {
        return EMPTY
    }
    const now = dayjs()
    const used = quota.credits_used
    const cap = quota.credit_limit
    const periodEnd = dayjs.utc(quota.period_end)
    const resetsOn = periodEnd.format('MMMM D')
    if (cap === 0) {
        // A $0 spend limit blocks everything; there is no ratio to project against.
        return { ...EMPTY, status: 'danger', exhausted: quota.exhausted, usedPct: 100, resetsOn }
    }
    const oneOffCredits = Math.max(inputs.oneOffCredits ?? 0, 0)
    const combinedDailyRate =
        Math.max(inputs.monthlyRateCredits ?? quota.scanners_monthly_credits, 0) / ESTIMATE_MONTH_DAYS
    const projectedAdditional = projectDemandCredits(quota, inputs) - used

    const projectedPeriodEndRatio = (used + projectedAdditional) / cap
    const committed = used + oneOffCredits
    // One-offs are charged as soon as they run, so they eat headroom before the rate does.
    const capReachDate =
        used < cap && committed >= cap
            ? now
            : combinedDailyRate > 0 && committed < cap
              ? now.add((cap - committed) / combinedDailyRate, 'day')
              : null
    const capReachInPeriod = !!capReachDate && !capReachDate.isAfter(periodEnd)

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
    const resetsOn = dayjs.utc(quota.period_end).format('MMMM D')
    if (quota.exhausted) {
        return { kind: 'exhausted', resetsOn, quota }
    }
    if (quota.credits_used / quota.credit_limit >= QUOTA_WARN_THRESHOLD) {
        return { kind: 'warning', resetsOn, quota }
    }
    return { kind: null }
}
