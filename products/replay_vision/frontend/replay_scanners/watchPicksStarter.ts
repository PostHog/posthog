import type { SessionRecordingType } from '~/types'

import { recordingScanBlock } from '../utils/scanEligibility'

export const BURST_MAX_RECORDINGS = 25
export const TARGET_MONTHLY_SCANS = 300
export const FREE_SCANNER_CREDIT_LIMIT = 1500
export const BUDGET_PRESETS = [1000, 2500, 5000] as const
const BURST_SWEEP_RESERVE_SCANS = 5

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
