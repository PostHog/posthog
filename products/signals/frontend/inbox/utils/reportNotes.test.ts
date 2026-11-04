import type { SignalReportArtefact } from '../types'
import { reportNotesFromArtefacts } from './reportNotes'

function artefact(overrides: Partial<SignalReportArtefact>): SignalReportArtefact {
    return { id: 'a', type: 'note', content: { note: 'text' }, created_at: '2026-06-10T09:00:00Z', ...overrides }
}

describe('reportNotesFromArtefacts', () => {
    it('keeps the notes people left, oldest first, and leaves agent and pipeline notes in Activity only', () => {
        const notes = reportNotesFromArtefacts([
            artefact({ id: 'scout-note', type: 'scout_note_left', created_at: '2026-06-11T09:00:00Z' }),
            artefact({ id: 'person-note', actor_kind: 'user', created_at: '2026-06-09T09:00:00Z' }),
            artefact({ id: 'task-note', actor_kind: 'task' }),
            artefact({ id: 'mcp-agent-note', actor_kind: 'agent' }),
            artefact({ id: 'legacy-note', actor_kind: 'system' }),
            artefact({ id: 'commit', type: 'commit', actor_kind: 'user' }),
        ])

        expect(notes.map((note) => note.id)).toEqual(['person-note', 'scout-note'])
    })
})
