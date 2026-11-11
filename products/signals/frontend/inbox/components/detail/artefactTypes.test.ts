import { SignalReportArtefact } from '../../types'
import { isInternalActivity } from './artefactTypes'

function artefact(type: string, actorKind?: SignalReportArtefact['actor_kind']): SignalReportArtefact {
    return { id: type, type, content: {}, created_at: '2026-06-11T10:00:00Z', actor_kind: actorKind }
}

describe('isInternalActivity', () => {
    it.each([
        ['an agent priority assessment', artefact('priority_judgment', 'task'), true],
        ['a code reference', artefact('code_reference', 'agent'), true],
        ['a monitoring measurement', artefact('check_observation', 'system'), true],
        ['a code reference a person added', artefact('code_reference', 'user'), false],
        ['a pushed commit', artefact('commit', 'task'), false],
        ['a note', artefact('note', 'user'), false],
        ['a check result', artefact('check_result', 'system'), false],
        ['a claim', artefact('work_claim', 'user'), false],
    ])('treats %s as internal: %s', (_name, entry, expected) => {
        expect(isInternalActivity(entry)).toBe(expected)
    })
})
