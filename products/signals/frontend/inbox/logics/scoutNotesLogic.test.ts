/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { PANEL_LOAD_TIMEOUT_MS } from '../utils/panelLoadTimeout'
import { scoutNotesLogic } from './scoutNotesLogic'

const NOTES_URL = '/api/projects/:team_id/signals/scout/notes/'
const SKILL_NAME = 'signals-scout-daily-digest'

describe('scoutNotesLogic', () => {
    let logic: ReturnType<typeof scoutNotesLogic.build>
    let reads: number

    beforeEach(() => {
        reads = 0
        // Neither read settles. What the test is about is which one owns the pane when the first
        // read's bound expires.
        useMocks({
            get: {
                [NOTES_URL]: () => {
                    reads += 1
                    return new Promise(() => {})
                },
            },
        })
        initKeaTests()
        jest.useFakeTimers()
        logic = scoutNotesLogic({ skillName: SKILL_NAME })
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    it('keeps an older read that times out from failing the pane under a newer one', async () => {
        logic.mount()

        // Saving a note reloads the list, so a second read can start part-way through the first.
        await jest.advanceTimersByTimeAsync(PANEL_LOAD_TIMEOUT_MS / 2)
        logic.actions.loadNotes()
        await jest.advanceTimersByTimeAsync(PANEL_LOAD_TIMEOUT_MS / 2)

        expect(reads).toEqual(2)
        // The first read's bound has expired and the second is still in flight, so the pane stays
        // on its spinner rather than offering a retry for a read that was already superseded.
        expect(logic.values.notesLoadFailed).toBe(false)
        expect(logic.values.notesLoading).toBe(true)
    })
})
