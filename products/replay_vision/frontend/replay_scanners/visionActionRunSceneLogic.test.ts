import { urls } from 'scenes/urls'

import type { RunObservationApi } from '../generated/api.schemas'
import { resolveObservationCitations } from './visionActionRunSceneLogic'

const obs = (index: number, id: string): RunObservationApi => ({
    index,
    id,
    session_id: 's',
    recording_subject_email: null,
    title: null,
    created_at: '2026-01-01T00:00:00Z',
})

const link = (id: string): string => urls.replayVisionObservation(id)

// Group members join on a no-break space so a `[2, 5, 33]` group can't wrap mid-bracket.
const NBSP = '\u00a0'

describe('resolveObservationCitations', () => {
    it('links a lone [obs N] marker as an [N] link and drops the ones that no longer resolve', () => {
        // obs 3 has no matching observation (deleted, or the model invented it) — it must be dropped, not
        // rendered as a dead `[3]` or misdirected to another row.
        const out = resolveObservationCitations('Friction here [obs 1]. Gone [obs 3].', [obs(1, 'aaa'), obs(2, 'bbb')])
        expect(out).toBe(`Friction here [\\[1\\]](${link('aaa')}). Gone .`)
    })

    it('collapses adjacent markers into one bracket group where every number is its own link', () => {
        const out = resolveObservationCitations('Direct to the button [obs 2] [obs 5] [obs 33].', [
            obs(2, 'aaa'),
            obs(5, 'bbb'),
            obs(33, 'ccc'),
        ])
        // Renders as `[2, 5, 33]`: brackets and commas live inside the link texts so the whole group
        // gets the superscript citation styling.
        expect(out).toBe(
            `Direct to the button [\\[2,](${link('aaa')})${NBSP}[5,](${link('bbb')})${NBSP}[33\\]](${link('ccc')}).`
        )
    })

    it('drops unresolvable markers from a group and keeps the brackets balanced', () => {
        const out = resolveObservationCitations('Here [obs 1] [obs 3] [obs 2].', [obs(1, 'aaa'), obs(2, 'bbb')])
        expect(out).toBe(`Here [\\[1,](${link('aaa')})${NBSP}[2\\]](${link('bbb')}).`)
    })

    it('cites a duplicated marker once so it does not read as extra evidence', () => {
        const out = resolveObservationCitations('Twice [obs 1] [obs 1] [obs 2].', [obs(1, 'aaa'), obs(2, 'bbb')])
        expect(out).toBe(`Twice [\\[1,](${link('aaa')})${NBSP}[2\\]](${link('bbb')}).`)
    })

    it('drops a group entirely when none of its markers resolve', () => {
        const out = resolveObservationCitations('Nothing left [obs 3] [obs 4].', [obs(1, 'aaa')])
        expect(out).toBe('Nothing left .')
    })

    it('does not collapse markers separated by other text or newlines', () => {
        const out = resolveObservationCitations('One [obs 1], two [obs 2]\n[obs 1]', [obs(1, 'aaa'), obs(2, 'bbb')])
        expect(out).toBe(`One [\\[1\\]](${link('aaa')}), two [\\[2\\]](${link('bbb')})\n[\\[1\\]](${link('aaa')})`)
    })

    it('maps a citation to its index, not its array position, after an earlier observation is deleted', () => {
        // obs 1 was deleted, so the array starts at index 2. `[obs 2]` must still resolve to id 'bbb'.
        const out = resolveObservationCitations('See [obs 2].', [obs(2, 'bbb'), obs(3, 'ccc')])
        expect(out).toBe(`See [\\[2\\]](${link('bbb')}).`)
    })
})
