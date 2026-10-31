import { Dayjs, dayjs } from 'lib/dayjs'

import type { VisionQuotaApi } from '../generated/api.schemas'
import type { ScanDrought } from './scanDrought'
import type { ReplayScanner } from './types'

// Mirrors the backend sweep schedule: a tick every 5 minutes over recordings that ended 35+ minutes ago.
export const SWEEP_INTERVAL_MINUTES = 5
const SWEEP_SETTLE_MINUTES = 35
// Slack past the expected watermark lag before a late sweep counts as delayed, so one slow tick doesn't flag it.
const DELAYED_GRACE_MINUTES = 60
// Matches the first-scan panel's cap: past it, a first sweep that never finished reads as delayed instead.
const STARTING_MAX_AGE_MINUTES = 60

export type ScannerStatus =
    | { kind: 'off'; reason: 'disabled' | 'no_sampling' }
    | { kind: 'limit_reached'; free_only: boolean; credit_limit: number | null; limit_from_free_credits: boolean }
    | { kind: 'quota_exhausted' }
    | { kind: 'filter_error'; message: string }
    | { kind: 'starting' }
    | { kind: 'delayed'; lastCheckedAt: Dayjs }
    | { kind: 'no_matches'; drought: ScanDrought }
    | { kind: 'throttled'; intervalMinutes: number; lastCheckedAt: Dayjs }
    | { kind: 'running'; intervalMinutes: number; lastCheckedAt: Dayjs }

export type ScannerStatusFields = Pick<
    ReplayScanner,
    | 'enabled'
    | 'sampling_rate'
    | 'limit_reached'
    | 'free_only'
    | 'credit_limit'
    | 'limit_from_free_credits'
    | 'sweep_throttle_factor'
    | 'created_at'
    | 'last_swept_at'
    | 'filter_error'
>

/** The one status the scanner page leads with. Earlier checks win, so a scanner that is off never also reads as stopped. */
export function scannerStatus(
    scanner: ScannerStatusFields,
    options: { quotaExhausted: boolean; drought: ScanDrought | null; now?: Dayjs }
): ScannerStatus {
    const now = options.now ?? dayjs()
    if (!scanner.enabled) {
        return { kind: 'off', reason: 'disabled' }
    }
    if (scanner.sampling_rate === 0) {
        return { kind: 'off', reason: 'no_sampling' }
    }
    if (scanner.limit_reached) {
        return {
            kind: 'limit_reached',
            free_only: !!scanner.free_only,
            credit_limit: scanner.credit_limit ?? null,
            limit_from_free_credits: !!scanner.limit_from_free_credits,
        }
    }
    if (options.quotaExhausted) {
        return { kind: 'quota_exhausted' }
    }
    if (scanner.filter_error) {
        return { kind: 'filter_error', message: scanner.filter_error }
    }
    const factor = Math.max(1, scanner.sweep_throttle_factor)
    const intervalMinutes = SWEEP_INTERVAL_MINUTES * factor
    const createdAt = dayjs(scanner.created_at)
    const lastSweptAt = dayjs(scanner.last_swept_at)
    // The watermark is seeded before created_at and only advances when a sweep tick finishes.
    if (lastSweptAt.isBefore(createdAt) && now.diff(createdAt, 'minute') < STARTING_MAX_AGE_MINUTES) {
        return { kind: 'starting' }
    }
    // The watermark trails wall clock by the settle window, so that lag is normal and not a delay.
    // Capped at now, so clock skew can't make the last check read as in the future.
    const settledAt = lastSweptAt.add(SWEEP_SETTLE_MINUTES, 'minute')
    const lastCheckedAt = settledAt.isAfter(now) ? now : settledAt
    if (now.diff(lastCheckedAt, 'minute') > intervalMinutes + DELAYED_GRACE_MINUTES) {
        return { kind: 'delayed', lastCheckedAt }
    }
    if (options.drought) {
        return { kind: 'no_matches', drought: options.drought }
    }
    if (factor > 1) {
        return { kind: 'throttled', intervalMinutes, lastCheckedAt }
    }
    return { kind: 'running', intervalMinutes, lastCheckedAt }
}

export interface SpendAgainstLimit {
    limit: number
    used: number
    usedPct: number
    /** True when the limit is the organization's free credits, not the scanner's own. */
    freeCredits?: boolean
}

export function spendAgainstLimit(
    scanner: Pick<ReplayScanner, 'credit_limit' | 'credits_used_against_limit'> & {
        free_only?: boolean
        limit_from_free_credits?: boolean
    },
    quota: VisionQuotaApi | null = null
): SpendAgainstLimit | null {
    const usedPct = (used: number, limit: number): number =>
        limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0
    const limit = scanner.credit_limit
    // A free-only scanner draws on the organization's free credits when they leave less room than its own limit.
    if (scanner.free_only && quota && (limit == null || scanner.limit_from_free_credits)) {
        const freeLimit = Math.min(quota.free_monthly_credits, quota.credit_limit ?? Infinity)
        const used = quota.credits_used
        return { limit: freeLimit, used, usedPct: usedPct(used, freeLimit), freeCredits: true }
    }
    if (limit == null) {
        return null
    }
    const used = scanner.credits_used_against_limit
    return { limit, used, usedPct: usedPct(used, limit) }
}
