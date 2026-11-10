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

    it('counts only the notes addressed to this scout as told', async () => {
        const note = (id: string, skill_name: string): Record<string, unknown> => ({
            id,
            content: 'A note',
            origin: 'report_discussion',
            skill_name,
            created_by_name: null,
            created_at: '2026-08-20T10:00:00Z',
            expires_at: null,
        })
        useMocks({
            get: {
                [NOTES_URL]: [note('own', SKILL_NAME), note('fleet-1', ''), note('fleet-2', '')],
            },
        })

        logic.mount()
        await jest.advanceTimersByTimeAsync(0)

        expect(logic.values.fleetWideNotes).toHaveLength(2)
        expect(logic.values.toldCount).toEqual(1)
    })
})
