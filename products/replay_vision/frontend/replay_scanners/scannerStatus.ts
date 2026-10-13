import { Dayjs, dayjs } from 'lib/dayjs'

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
    | { kind: 'limit_reached' }
    | { kind: 'quota_exhausted' }
    | { kind: 'starting' }
    | { kind: 'delayed'; lastCheckedAt: Dayjs }
    | { kind: 'no_matches'; drought: ScanDrought }
    | { kind: 'throttled'; intervalMinutes: number; lastCheckedAt: Dayjs }
    | { kind: 'running'; intervalMinutes: number; lastCheckedAt: Dayjs }

export type ScannerStatusFields = Pick<
    ReplayScanner,
    'enabled' | 'sampling_rate' | 'limit_reached' | 'sweep_throttle_factor' | 'created_at' | 'last_swept_at'
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
        return { kind: 'limit_reached' }
    }
    if (options.quotaExhausted) {
        return { kind: 'quota_exhausted' }
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
}

export function spendAgainstLimit(
    scanner: Pick<ReplayScanner, 'credit_limit' | 'credits_used_against_limit'>
): SpendAgainstLimit | null {
    const limit = scanner.credit_limit
    if (limit == null) {
        return null
    }
    const used = scanner.credits_used_against_limit
    return { limit, used, usedPct: limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0 }
}
