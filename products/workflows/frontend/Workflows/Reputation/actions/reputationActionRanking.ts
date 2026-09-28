import type { RateKind } from '../reputationUtils'
import type { ReputationActionSeverity } from './reputationActionTypes'

const SEVERITY_ORDER: Record<ReputationActionSeverity, number> = { high: 0, medium: 1, low: 2 }

// Within one severity, what blocks all sending comes first, then what the provider named, then
// the rates we measure. Low-impact DNS findings sit below workflows over a line because a missing
// record rarely causes the bounces or complaints those workflows already show.
const SLOT_ORDER = {
    sendingStopped: 0,
    pausedWorkflow: 1,
    highFinding: 2,
    providerVerdict: 3,
    projectRate: 4,
    workflowRate: 5,
    lowFinding: 6,
    lowDnsFinding: 7,
    providerRate: 8,
    optionalSetup: 9,
} as const

export type ReputationActionSlot = keyof typeof SLOT_ORDER

// Complaints come first: their lines are far lower than the bounce lines, and the endpoint ranks
// workflows by complaint rate for the same reason.
const RATE_KIND_ORDER: Record<RateKind, number> = { complaint: 0, bounce: 1 }
const NO_RATE_KIND_ORDER = 2

export interface ReputationActionRank {
    severity: ReputationActionSeverity
    slot: ReputationActionSlot
    rateKind?: RateKind
    /** How far past its line the row is. Bigger sorts first within the same slot. */
    magnitude?: number
}

export function compareReputationActionRanks(a: ReputationActionRank, b: ReputationActionRank): number {
    const kindOrder = (rank: ReputationActionRank): number =>
        rank.rateKind ? RATE_KIND_ORDER[rank.rateKind] : NO_RATE_KIND_ORDER
    return (
        SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] ||
        SLOT_ORDER[a.slot] - SLOT_ORDER[b.slot] ||
        kindOrder(a) - kindOrder(b) ||
        (b.magnitude ?? 0) - (a.magnitude ?? 0)
    )
}
