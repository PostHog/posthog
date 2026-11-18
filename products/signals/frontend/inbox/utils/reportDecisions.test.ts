import type { SignalReportArtefact } from '../types'
import { reportDecisionAttributions } from './reportDecisions'

const person = { id: 1, uuid: 'person-1', distinct_id: 'person-1', first_name: 'Jane', email: 'jane@example.com' }

function artefact(overrides: Partial<SignalReportArtefact>): SignalReportArtefact {
    return {
        id: 'a',
        type: 'priority_judgment',
        content: {},
        created_at: '2026-06-10T09:00:00Z',
        actor_kind: 'task',
        ...overrides,
    }
}

describe('reportDecisionAttributions', () => {
    it.each([
        {
            name: 'the newest agent choice with its reason',
            artefacts: [
                artefact({
                    type: 'repo_selection',
                    content: { repository: 'example/web', reason: 'Newer reason.' },
                    created_at: '2026-06-11T09:00:00Z',
                }),
                artefact({ type: 'repo_selection', content: { repository: 'example/api', reason: 'Older reason.' } }),
            ],
            decision: 'repository' as const,
            expected: { person: null, setAt: '2026-06-11T09:00:00Z', reason: 'Newer reason.', previousValue: null },
        },
        {
            name: 'a person change with the last different value before it',
            artefacts: [
                artefact({ content: { priority: 'P3', explanation: 'Agent reason.' } }),
                artefact({
                    content: { priority: 'P2', explanation: 'Agent reason.' },
                    created_at: '2026-06-11T09:00:00Z',
                }),
                artefact({
                    content: { priority: 'P1', explanation: 'Priority changed in the inbox.' },
                    created_at: '2026-06-12T09:00:00Z',
                    actor_kind: 'user',
                    created_by: person,
                }),
            ],
            decision: 'priority' as const,
            expected: { person, setAt: '2026-06-12T09:00:00Z', reason: null, previousValue: 'P2' },
        },
        {
            name: 'an agent acting for a person as the agent',
            artefacts: [
                artefact({
                    content: { priority: 'P1', explanation: 'Agent reason.' },
                    actor_kind: 'agent',
                    created_by: person,
                }),
            ],
            decision: 'priority' as const,
            expected: { person: null, setAt: '2026-06-10T09:00:00Z', reason: 'Agent reason.', previousValue: null },
        },
        {
            name: 'no history as null',
            artefacts: [artefact({ content: { priority: 'P1' } })],
            decision: 'repository' as const,
            expected: null,
        },
    ])('reads $name', ({ artefacts, decision, expected }) => {
        expect(reportDecisionAttributions(artefacts)[decision]).toEqual(expected)
    })
})
