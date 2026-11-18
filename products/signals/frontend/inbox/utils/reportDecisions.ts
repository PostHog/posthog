import type { UserBasicType } from '~/types'

import type { SignalReportArtefact } from '../types'

export type ReportDecision = 'repository' | 'priority'

export interface ReportDecisionAttribution {
    /** The person who set the current value, or null when an agent or the pipeline set it. */
    person: UserBasicType | null
    setAt: string
    /** The agent's stated reason. Null for a value a person set, since the row already names them. */
    reason: string | null
    previousValue: string | null
}

export type ReportDecisionAttributions = Record<ReportDecision, ReportDecisionAttribution | null>

/** Each decision is a history of artefacts of one type, and the newest one holds the current value. */
const DECISION_ARTEFACTS: Record<ReportDecision, { type: string; valueKey: string; reasonKey: string }> = {
    repository: { type: 'repo_selection', valueKey: 'repository', reasonKey: 'reason' },
    priority: { type: 'priority_judgment', valueKey: 'priority', reasonKey: 'explanation' },
}

function nonEmptyString(value: unknown): string | null {
    return typeof value === 'string' && value.trim() ? value : null
}

function decisionAttribution(
    artefacts: SignalReportArtefact[],
    decision: ReportDecision
): ReportDecisionAttribution | null {
    const { type, valueKey, reasonKey } = DECISION_ARTEFACTS[decision]
    const history = artefacts
        .filter((artefact) => artefact.type === type)
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
    const latest = history[0]
    if (!latest) {
        return null
    }
    // An agent acting for a person also carries that person in `created_by`, so only `actor_kind`
    // tells a person's own change apart from the agent's.
    const person = latest.actor_kind === 'user' ? (latest.created_by ?? null) : null
    const value = nonEmptyString(latest.content?.[valueKey])
    const previousValue = person
        ? (history
              .slice(1)
              .map((artefact) => nonEmptyString(artefact.content?.[valueKey]))
              .find((earlier) => earlier !== null && earlier !== value) ?? null)
        : null
    return {
        person,
        setAt: latest.created_at,
        reason: person ? null : nonEmptyString(latest.content?.[reasonKey]),
        previousValue,
    }
}

export function reportDecisionAttributions(artefacts: SignalReportArtefact[]): ReportDecisionAttributions {
    return {
        repository: decisionAttribution(artefacts, 'repository'),
        priority: decisionAttribution(artefacts, 'priority'),
    }
}
