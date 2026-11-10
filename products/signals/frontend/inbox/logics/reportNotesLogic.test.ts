/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { EVERY_SCOUT, reportNotesLogic } from './reportNotesLogic'

const NOTES_URL = '/api/projects/:team_id/signals/scout/notes/'
const ARTEFACTS_URL = '/api/projects/:team_id/signals/reports/:report_id/artefacts/'
const REPORT_ID = '0b9f8a52-3c1e-4d7a-9f60-2a4e1c7b8d01'
const REPORT_SCOUT = 'signals-scout-checkout'

describe('reportNotesLogic', () => {
    let logic: ReturnType<typeof reportNotesLogic.build>
    let listQueries: URLSearchParams[]
    let scoutNoteBodies: Record<string, unknown>[]
    let artefactBodies: Record<string, unknown>[]
    let notesOnServer: Record<string, unknown>[]

    beforeEach(() => {
        listQueries = []
        scoutNoteBodies = []
        artefactBodies = []
        notesOnServer = []
        useMocks({
            get: {
                [NOTES_URL]: ({ request }) => {
                    listQueries.push(new URL(request.url).searchParams)
                    return [200, notesOnServer]
                },
                '/api/projects/:team_id/signals/scout/configs/': () => [200, []],
            },
            post: {
                [NOTES_URL]: async ({ request }) => {
                    const body = (await request.json()) as Record<string, unknown>
                    scoutNoteBodies.push(body)
                    return [201, { id: 'note-1', origin: 'human', ...body }]
                },
                [ARTEFACTS_URL]: async ({ request }) => {
                    const body = (await request.json()) as Record<string, unknown>
                    artefactBodies.push(body)
                    return [201, { id: 'artefact-1', type: 'note', content: body.content }]
                },
            },
        })
        initKeaTests()
        logic = reportNotesLogic({ reportId: REPORT_ID })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('finds notes by the report id they quote, across every scout', async () => {
        await expectLogic(logic).toFinishAllListeners()

        // A `skill_name` here would miss notes sent to other scouts, so their entries would read inactive.
        expect(listQueries[0].get('text')).toEqual(REPORT_ID)
        expect(listQueries[0].has('skill_name')).toBe(false)
    })

    it.each([
        {
            name: 'a note for the report scout goes to the scouts, tied to the report',
            scoutTarget: REPORT_SCOUT,
            scoutNotes: [{ content: 'Focus on the new checkout flow', report_id: REPORT_ID, skill_name: REPORT_SCOUT }],
            artefacts: [],
        },
        {
            name: 'a note for every scout leaves the target blank',
            scoutTarget: EVERY_SCOUT,
            scoutNotes: [{ content: 'Focus on the new checkout flow', report_id: REPORT_ID }],
            artefacts: [],
        },
        {
            name: 'a note kept on the report never reaches the scouts',
            scoutTarget: null,
            scoutNotes: [],
            artefacts: [{ artefact_type: 'note', content: { note: 'Focus on the new checkout flow' } }],
        },
    ])('$name', async ({ scoutTarget, scoutNotes, artefacts }) => {
        await logic.asyncActions.addNote('Focus on the new checkout flow', scoutTarget, REPORT_SCOUT)

        expect(scoutNoteBodies).toEqual(scoutNotes)
        expect(artefactBodies).toEqual(artefacts)
        expect(logic.values.lastSaveFailed).toBe(false)
    })

    it('reads the notes back when a retire fails, since the delete may still have landed', async () => {
        notesOnServer = [{ id: 'note-1', origin: 'human', content: `About ${REPORT_ID}` }]
        logic.actions.loadNotes()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.activeNoteIds.has('note-1')).toBe(true)

        // The delete landed and the response did not, so the optimistic flag alone would be undone
        // and the entry would read active again.
        useMocks({ delete: { [`${NOTES_URL}:id/`]: () => [500, {}] } })
        notesOnServer = []
        logic.actions.retireNote('note-1')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.activeNoteIds.has('note-1')).toBe(false)
    })
})
