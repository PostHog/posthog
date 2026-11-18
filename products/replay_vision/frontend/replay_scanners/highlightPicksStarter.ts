import type { SessionRecordingType } from '~/types'

import type { EstimateResponseApi } from '../generated/api.schemas'
import { recordingScanBlock } from '../utils/scanEligibility'
import type { SummarizerScannerConfig } from './types'

export const BURST_MAX_RECORDINGS = 25
export const TARGET_MONTHLY_SCANS = 300
export const FREE_SCANNER_CREDIT_LIMIT = 1500
export const BUDGET_PRESETS = [1000, 2500, 5000] as const
const BURST_SWEEP_RESERVE_SCANS = 5
export interface WeeklyVolume {
    recorded: number
    hours: number | null
}

export function weeklyVolume(
    estimate: Pick<EstimateResponseApi, 'matched_sessions_in_window' | 'window_days'> | null,
    recordings: readonly Pick<SessionRecordingType, 'recording_duration'>[]
): WeeklyVolume | null {
    if (!estimate || estimate.window_days <= 0) {
        return null
    }
    const recorded = Math.round((estimate.matched_sessions_in_window / estimate.window_days) * 7)
    if (recorded <= 0) {
        return null
    }
    const durations = recordings
        .map((recording) => recording.recording_duration)
        .filter((duration): duration is number => typeof duration === 'number' && duration > 0)
    const hours =
        durations.length > 0
            ? (recorded * (durations.reduce((sum, duration) => sum + duration, 0) / durations.length)) / 3600
            : null
    return { recorded, hours }
}
export const QUICKSTART_SCANNER = {
    key: 'session_highlights',
    name: 'Session highlights',
    description: 'Summarizes each new recording and flags the ones worth watching.',
    scanner_type: 'summarizer' as const,
    scanner_config: {
        prompt: 'Summarize what the user was trying to do in this session and what got in their way. Call out anything unusual, surprising, or broken: errors, dead ends, repeated attempts, confusion, or an outcome that does not match what they set out to do. Be concrete and do not speculate.',
        length: 'medium',
    } satisfies SummarizerScannerConfig,
}

export type StarterSpendMode = 'free' | 'budget'

export interface BurstPlan {
    sessionIds: string[]
    credits: number
}

export function planBurst(
    recordings: readonly Pick<SessionRecordingType, 'id' | 'recording_duration' | 'active_seconds' | 'ongoing'>[],
    creditsPerObservation: number,
    spendMode: StarterSpendMode,
    freeCreditsLeft: number | null,
    budget: number | null
): BurstPlan {
    const eligible = recordings.filter((recording) => recordingScanBlock(recording) === null).map((r) => r.id)
    const allowance = spendMode === 'free' ? freeCreditsLeft : budget
    const affordable =
        allowance === null
            ? BURST_MAX_RECORDINGS
            : Math.max(0, Math.floor(allowance / creditsPerObservation) - BURST_SWEEP_RESERVE_SCANS)
    const sessionIds = eligible.slice(0, Math.min(BURST_MAX_RECORDINGS, affordable))
    return { sessionIds, credits: sessionIds.length * creditsPerObservation }
}

export function samplingRateForTarget(estimatedMonthlyAtFullRate: number | null, targetMonthly: number): number {
    if (estimatedMonthlyAtFullRate === null || estimatedMonthlyAtFullRate <= targetMonthly) {
        return 1
    }
    return Math.max(0.01, Math.round((targetMonthly / estimatedMonthlyAtFullRate) * 100) / 100)
}

export function starterSpendMode(freeCreditsLeft: number | null, creditsPerObservation: number): StarterSpendMode {
    return freeCreditsLeft !== null && freeCreditsLeft < creditsPerObservation ? 'budget' : 'free'
}
