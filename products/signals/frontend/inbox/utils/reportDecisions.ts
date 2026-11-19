import type { ReportDecisionSetByApi, ReportDecisionsApi } from 'products/signals/frontend/generated/api.schemas'

import type { SignalReportArtefact } from '../types'

export type ReportDecision = 'repository' | 'priority'

export interface ReportDecisionAttribution {
    /** The person who set the current value, or null when a PostHog task or the pipeline set it. */
    person: ReportDecisionSetByApi['user']
    /** The external agent the person set it through, or null when they set it themselves. */
    agent: string | null
    setAt: string
    /** The agent's stated reason. Null for a value a person set in PostHog, since the row already names them. */
    reason: string | null
    /** The last different value before a person's change. Null until the report's history loads. */
    previousValue: string | null
}

export type ReportDecisionAttributions = Record<ReportDecision, ReportDecisionAttribution | null>

/** The artefact history behind each decision. The serializer reads the newest row, this reads the ones before it. */
const DECISION_HISTORY: Record<ReportDecision, { type: string; valueKey: string }> = {
    repository: { type: 'repo_selection', valueKey: 'repository' },
    priority: { type: 'priority_judgment', valueKey: 'priority' },
}

function nonEmptyString(value: unknown): string | null {
    return typeof value === 'string' && value.trim() ? value : null
}

function previousDecisionValue(
    artefacts: SignalReportArtefact[],
    decision: ReportDecision,
    current: string | null
): string | null {
    const { type, valueKey } = DECISION_HISTORY[decision]
    return (
        artefacts
            .filter((artefact) => artefact.type === type)
            .sort((a, b) => b.created_at.localeCompare(a.created_at))
            .map((artefact) => nonEmptyString(artefact.content?.[valueKey]))
            .find((value) => value !== null && value !== current) ?? null
    )
}

function decisionAttribution(
    decisions: ReportDecisionsApi,
    artefacts: SignalReportArtefact[] | null,
    decision: ReportDecision
): ReportDecisionAttribution | null {
    const current = decisions[decision]
    if (!current) {
        return null
    }
    const { kind, user, agent } = current.set_by
    // The same rule the agent stages use to keep a decision: any write with a person behind it,
    // including one made through that person's own agent.
    const person = user ?? null
    return {
        person,
        agent: person && kind === 'agent' ? nonEmptyString(agent) : null,
        setAt: current.set_at,
        reason: kind === 'user' ? null : nonEmptyString(current.reason),
        previousValue: person && artefacts ? previousDecisionValue(artefacts, decision, current.value) : null,
    }
}

export function reportDecisionAttributions(
    decisions: ReportDecisionsApi | null | undefined,
    artefacts: SignalReportArtefact[] | null
): ReportDecisionAttributions | null {
    if (!decisions) {
        return null
    }
    return {
        repository: decisionAttribution(decisions, artefacts, 'repository'),
        priority: decisionAttribution(decisions, artefacts, 'priority'),
    }
}
