import { Dayjs, dayjs } from 'lib/dayjs'

import { type ReplayScannerApi, type ScannerStatusReasonEnumApi, type VisionQuotaApi } from '../generated/api.schemas'
import type { RecordingsBlock } from '../logics/replayRecordingsLogic'
import { freeCreditsAllowance } from '../utils/quotaProjection'
import type { ScanDrought } from './scanDrought'
import type { ReplayScanner } from './types'

// Mirrors the backend sweep schedule: at most one tick every 5 minutes, over recordings that ended 35+ minutes ago.
export const SWEEP_INTERVAL_MINUTES = 5
// Kept in sync with SWEEP_SETTLE in backend/scanner_status.py.
const SWEEP_SETTLE_MINUTES = 35

export type ScannerStatus =
    | { kind: 'off'; reason: ScannerOffReason | null }
    | { kind: 'no_sampling' }
    | { kind: 'replay_off' }
    | { kind: 'no_recordings' }
    | { kind: 'limit_reached'; freeCredits: boolean }
    | { kind: 'quota_exhausted' }
    | { kind: 'filter_error'; message: string }
    | { kind: 'starting' }
    | { kind: 'paused'; reason: ScannerStatusReasonEnumApi | null }
    | { kind: 'delayed'; lastCheckedAt: Dayjs }
    | { kind: 'no_matches'; drought: ScanDrought }
    | { kind: 'throttled'; intervalMinutes: number; lastCheckedAt: Dayjs }
    | { kind: 'running'; intervalMinutes: number; lastCheckedAt: Dayjs }

export type ScannerStatusFields = Pick<
    ReplayScanner,
    'status' | 'status_reason' | 'filter_error' | 'sweep_interval_minutes' | 'last_swept_at'
>

const OFF_REASONS = [
    'manual',
    'free_credits_used',
    'no_ai_consent',
    'creator_lost_access',
    'experiment_deleted',
] as const

/** The `status_reason` values an `off` scanner can carry. */
export type ScannerOffReason = Extract<ScannerStatusReasonEnumApi, (typeof OFF_REASONS)[number]>

function isOffReason(reason: ScannerStatusReasonEnumApi | null): reason is ScannerOffReason {
    return reason !== null && (OFF_REASONS as readonly string[]).includes(reason)
}

export function isOffByChoice(scanner: Pick<ReplayScannerApi, 'status' | 'status_reason'> | null | undefined): boolean {
    return !!scanner && scanner.status === 'off' && (!scanner.status_reason || scanner.status_reason === 'manual')
}

// A sweep tick runs every few minutes, so checking once a minute keeps a status close without a request storm.
export const STATUS_POLL_MS = 60_000

export function isOffForAReason(status: ScannerStatus | undefined): boolean {
    return status?.kind === 'off' && !!status.reason && status.reason !== 'manual'
}

/**
 * The one status the scanner page leads with. The backend works out the scanner's own status, and this adds the
 * project-wide causes and the no-matches check it can't see, each where it outranks the scanner's own.
 */
export function scannerStatus(
    scanner: ScannerStatusFields,
    options: {
        quotaExhausted: boolean
        drought: ScanDrought | null
        recordingsBlock?: RecordingsBlock | null
        now?: Dayjs
    }
): ScannerStatus {
    const reason = scanner.status_reason ?? null
    if (scanner.status === 'off') {
        return {
            kind: 'off',
            reason: isOffReason(reason) ? reason : null,
        }
    }
    if (scanner.status === 'no_sampling') {
        return { kind: 'no_sampling' }
    }
    // With no recordings coming in, every status below would blame the scanner for a project-wide gap.
    if (options.recordingsBlock === 'replay-off') {
        return { kind: 'replay_off' }
    }
    if (options.recordingsBlock === 'no-recordings') {
        return { kind: 'no_recordings' }
    }
    if (scanner.status === 'limit_reached') {
        return { kind: 'limit_reached', freeCredits: reason === 'free_credits_used' }
    }
    if (options.quotaExhausted) {
        return { kind: 'quota_exhausted' }
    }
    const now = options.now ?? dayjs()
    // The watermark trails wall clock by the settle window, so that lag is normal and not a delay.
    // Capped at now, so clock skew can't make the last check read as in the future.
    const settledAt = dayjs(scanner.last_swept_at).add(SWEEP_SETTLE_MINUTES, 'minute')
    const lastCheckedAt = settledAt.isAfter(now) ? now : settledAt
    const intervalMinutes = scanner.sweep_interval_minutes ?? SWEEP_INTERVAL_MINUTES
    switch (scanner.status) {
        case 'filter_error':
            return { kind: 'filter_error', message: scanner.filter_error ?? '' }
        case 'paused':
            return { kind: 'paused', reason }
        case 'starting':
            return { kind: 'starting' }
        case 'delayed':
            return { kind: 'delayed', lastCheckedAt }
    }
    if (options.drought) {
        return { kind: 'no_matches', drought: options.drought }
    }
    return { kind: scanner.status === 'throttled' ? 'throttled' : 'running', intervalMinutes, lastCheckedAt }
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
    const freeLimit = freeCreditsAllowance(quota)
    if (scanner.free_only && quota && freeLimit !== null && (limit == null || scanner.limit_from_free_credits)) {
        const used = quota.credits_used
        return { limit: freeLimit, used, usedPct: usedPct(used, freeLimit), freeCredits: true }
    }
    if (limit == null) {
        return null
    }
    const used = scanner.credits_used_against_limit
    return { limit, used, usedPct: usedPct(used, limit) }
}
