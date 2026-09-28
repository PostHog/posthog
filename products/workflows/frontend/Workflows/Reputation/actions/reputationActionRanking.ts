import { RATE_KIND_LIST, type RateKind } from '../reputationUtils'
import type { ReputationActionSeverity } from './reputationActionTypes'

const SEVERITY_ORDER: Record<ReputationActionSeverity, number> = { high: 0, medium: 1, low: 2 }

// Within one severity, what blocks all sending comes first, then what the provider named, then
// the rates we measure. Low-impact findings sit below workflows over a line because the provider
// rarely acts on them alone. Low-impact DNS findings sit lowest of those, because a missing record
// rarely causes the bounces or complaints the rows above them already show.
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

type ReputationActionSlot = keyof typeof SLOT_ORDER

export interface ReputationActionRank {
    severity: ReputationActionSeverity
    slot: ReputationActionSlot
    rateKind?: RateKind
    /** How far past its line the row is. Bigger sorts first within the same slot. */
    magnitude?: number
    /** Settles what is still tied, for example the provider's own order of its findings. */
    order?: number
}

export function compareReputationActionRanks(a: ReputationActionRank, b: ReputationActionRank): number {
    const kindOrder = (rank: ReputationActionRank): number =>
        rank.rateKind ? RATE_KIND_LIST.indexOf(rank.rateKind) : RATE_KIND_LIST.length
    return (
        SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] ||
        SLOT_ORDER[a.slot] - SLOT_ORDER[b.slot] ||
        kindOrder(a) - kindOrder(b) ||
        (b.magnitude ?? 0) - (a.magnitude ?? 0) ||
        (a.order ?? 0) - (b.order ?? 0)
    )
}
