import type { ReportDecisionSetByApi, ReportDecisionsApi } from 'products/signals/frontend/generated/api.schemas'

import type { SignalReportArtefact } from '../types'
import { reportDecisionAttributions } from './reportDecisions'

const person = { id: 1, uuid: 'person-1', first_name: 'Jane', last_name: 'Doe', email: 'jane@example.com' }

function decisions(setBy: Partial<ReportDecisionSetByApi>, value = 'P1'): ReportDecisionsApi {
    return {
        repository: null,
        priority: {
            value: value as 'P1',
            reason: 'Stored reason.',
            set_at: '2026-06-12T09:00:00Z',
            set_by: { kind: 'task', user: null, agent: null, task_id: null, ...setBy },
        },
        actionability: null,
        already_addressed: null,
    }
}

function judgment(priority: string, createdAt: string): SignalReportArtefact {
    return {
        id: createdAt,
        type: 'priority_judgment',
        content: { priority },
        created_at: createdAt,
        actor_kind: 'task',
    }
}

const history = [
    judgment('P3', '2026-06-10T09:00:00Z'),
    judgment('P2', '2026-06-11T09:00:00Z'),
    judgment('P1', '2026-06-12T09:00:00Z'),
]

describe('reportDecisionAttributions', () => {
    it.each([
        {
            name: 'a task choice with its reason and no previous value',
            decisions: decisions({ kind: 'task', task_id: 'task-1' }),
            artefacts: history,
            expected: { person: null, agent: null, reason: 'Stored reason.', previousValue: null },
        },
        {
            name: 'a person change with the last different value before it',
            decisions: decisions({ kind: 'user', user: person }),
            artefacts: history,
            expected: { person, agent: null, reason: null, previousValue: 'P2' },
        },
        {
            name: "a person's own agent as the person, with the agent and its reason",
            decisions: decisions({ kind: 'agent', user: person, agent: 'Codex' }),
            artefacts: history,
            expected: { person, agent: 'Codex', reason: 'Stored reason.', previousValue: 'P2' },
        },
        {
            name: 'a person change before the history loads without a previous value',
            decisions: decisions({ kind: 'user', user: person }),
            artefacts: null,
            expected: { person, agent: null, reason: null, previousValue: null },
        },
        {
            name: 'a person change against a history that predates it',
            decisions: decisions({ kind: 'user', user: person }, 'P0'),
            artefacts: history,
            expected: { person, agent: null, reason: null, previousValue: 'P1' },
        },
    ])('reads $name', ({ decisions, artefacts, expected }) => {
        expect(reportDecisionAttributions(decisions, artefacts)?.priority).toEqual({
            setAt: '2026-06-12T09:00:00Z',
            ...expected,
        })
    })

    it('reads a decision with no history as null, and a report without decisions as null', () => {
        expect(reportDecisionAttributions(decisions({}), [])?.repository).toBeNull()
        expect(reportDecisionAttributions(undefined, history)).toBeNull()
    })
})
