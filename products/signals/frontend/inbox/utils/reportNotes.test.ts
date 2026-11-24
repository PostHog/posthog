import type { SignalReportArtefact } from '../types'
import { reportNotesFromArtefacts, splitNoteMentions } from './reportNotes'

function artefact(overrides: Partial<SignalReportArtefact>): SignalReportArtefact {
    return { id: 'a', type: 'note', content: { note: 'text' }, created_at: '2026-06-10T09:00:00Z', ...overrides }
}

describe('reportNotes', () => {
    describe('reportNotesFromArtefacts', () => {
        it('keeps the notes people left, oldest first, and leaves agent and pipeline notes in Activity only', () => {
            const notes = reportNotesFromArtefacts([
                artefact({
                    id: 'scout-note',
                    type: 'scout_note_left',
                    actor_kind: 'user',
                    created_at: '2026-06-11T09:00:00Z',
                }),
                artefact({ id: 'agent-scout-note', type: 'scout_note_left', actor_kind: 'agent' }),
                artefact({ id: 'task-scout-note', type: 'scout_note_left', actor_kind: 'task' }),
                artefact({ id: 'person-note', actor_kind: 'user', created_at: '2026-06-09T09:00:00Z' }),
                artefact({ id: 'task-note', actor_kind: 'task' }),
                artefact({ id: 'mcp-agent-note', actor_kind: 'agent' }),
                artefact({ id: 'legacy-note', actor_kind: 'system' }),
                artefact({ id: 'commit', type: 'commit', actor_kind: 'user' }),
            ])

            expect(notes.map((note) => note.id)).toEqual(['person-note', 'scout-note'])
        })
    })

    describe('splitNoteMentions', () => {
        const roleId = '0190f3a1-7d2e-7c41-9a3b-5e6f7a8b9c0d'

        it.each([
            ['plain text', 'no mentions here', [{ kind: 'text', text: 'no mentions here' }]],
            [
                'a member and a role',
                `@member:202 and @role:${roleId} look`,
                [
                    { kind: 'member', id: 202 },
                    { kind: 'text', text: ' and ' },
                    { kind: 'role', id: roleId },
                    { kind: 'text', text: ' look' },
                ],
            ],
            ['a token glued to a word', 'mail me@member:202', [{ kind: 'text', text: 'mail me@member:202' }]],
            ['a role with a number id', '@role:12', [{ kind: 'text', text: '@role:12' }]],
        ])('splits %s', (_name, text, segments) => {
            expect(splitNoteMentions(text)).toEqual(segments)
        })
    })
})
