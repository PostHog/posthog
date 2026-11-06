import type {
    GoalScoutDetailApi,
    GoalScoutEvidenceApi,
    GoalScoutEvidenceKindEnumApi,
    GoalScoutWorkApi,
} from 'products/signals/frontend/generated/api.schemas'

import { isOpen } from './status'

export const ASSESSMENT_LABELS: Record<string, string> = {
    supported: 'High confidence',
    not_supported: 'Low confidence',
    pending: 'Checking',
    no_verdict: 'No verdict',
}

const EVIDENCE_ORDER: Partial<Record<GoalScoutEvidenceKindEnumApi, number>> = {
    replay: 0,
    insight: 1,
    chart: 1,
    error: 2,
    experiment: 3,
}

const ASSESSMENT_ORDER: Record<string, number> = { supported: 0, pending: 1, '': 2, not_supported: 3 }

const ASSESSMENT_MARKER = /^\s*(?:not supported|supported)\s*[.:]\s*/i

type GoalWork = Pick<GoalScoutDetailApi, 'work'>

export function ideaAssessment(item: GoalScoutWorkApi): string {
    return item.assessment === 'pending' && item.report_id ? 'no_verdict' : item.assessment
}

export function ideaEvidence(item: GoalScoutWorkApi): GoalScoutEvidenceApi[] {
    return item.evidence
        .map((evidence, index) => ({ evidence, index, rank: EVIDENCE_ORDER[evidence.kind] }))
        .filter(
            (entry): entry is { evidence: GoalScoutEvidenceApi; index: number; rank: number } =>
                entry.rank !== undefined
        )
        .sort((a, b) => a.rank - b.rank || a.index - b.index)
        .map((entry) => entry.evidence)
}

function ideaReport(item: GoalScoutWorkApi): string {
    return item.summary.replace(ASSESSMENT_MARKER, '').trim()
}

export function ideaLead(item: GoalScoutWorkApi): string {
    const [lead = ''] = ideaReport(item).split(/\s\*\*[A-Z]/)
    return lead.trim()
}

export function ideaReason(item: GoalScoutWorkApi): string {
    const [first = ''] = ideaReport(item).split(/(?<=[.!?])\s+/)
    return first.trim()
}

export function isBuilt(item: GoalScoutWorkApi): boolean {
    return item.stage !== 'proposed' && item.stage !== 'dismissed'
}

export function firstSupportedIdea(ideas: GoalScoutWorkApi[]): string | null {
    return ideas.find((item) => item.assessment === 'supported')?.id ?? null
}

export function waitingIdeas(goal: GoalWork): GoalScoutWorkApi[] {
    return goal.work
        .filter((item) => item.kind === 'idea' && item.stage === 'proposed')
        .map((item, index) => ({ item, index }))
        .sort((a, b) => ASSESSMENT_ORDER[a.item.assessment] - ASSESSMENT_ORDER[b.item.assessment] || a.index - b.index)
        .map(({ item }) => item)
}

export function dismissedIdeas(goal: GoalWork): GoalScoutWorkApi[] {
    return goal.work.filter((item) => item.kind === 'idea' && item.stage === 'dismissed')
}

export function ideaInProgress(goal: GoalWork): GoalScoutWorkApi | null {
    return goal.work.find((item) => item.kind === 'idea' && isOpen(item)) ?? null
}
