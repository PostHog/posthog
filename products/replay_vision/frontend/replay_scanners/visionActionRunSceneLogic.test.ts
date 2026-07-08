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

describe('resolveObservationCitations', () => {
    it('links resolvable [obs N] markers and drops the ones that no longer resolve', () => {
        // obs 3 has no matching observation (deleted, or the model invented it) — it must be dropped, not
        // rendered as a dead `[obs 3]` or misdirected to another row.
        const out = resolveObservationCitations('Friction here [obs 1] [obs 2]. Gone [obs 3].', [
            obs(1, 'aaa'),
            obs(2, 'bbb'),
        ])
        expect(out).toBe(
            `Friction here [obs 1](${urls.replayVisionObservation('aaa')}) [obs 2](${urls.replayVisionObservation(
                'bbb'
            )}). Gone .`
        )
    })

    it('maps a citation to its index, not its array position, after an earlier observation is deleted', () => {
        // obs 1 was deleted, so the array starts at index 2. `[obs 2]` must still resolve to id 'bbb'.
        const out = resolveObservationCitations('See [obs 2].', [obs(2, 'bbb'), obs(3, 'ccc')])
        expect(out).toBe(`See [obs 2](${urls.replayVisionObservation('bbb')}).`)
    })
})
