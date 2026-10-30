/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { EVERY_SCOUT, reportNotesLogic } from './reportNotesLogic'

const NOTES_URL = '/api/projects/:team_id/signals/scout/notes/'
const REPORT_ID = '0b9f8a52-3c1e-4d7a-9f60-2a4e1c7b8d01'
const REPORT_SCOUT = 'signals-scout-checkout'

describe('reportNotesLogic', () => {
    let logic: ReturnType<typeof reportNotesLogic.build>
    let listQueries: URLSearchParams[]
    let createdBodies: Record<string, unknown>[]

    beforeEach(() => {
        listQueries = []
        createdBodies = []
        useMocks({
            get: {
                [NOTES_URL]: ({ request }) => {
                    listQueries.push(new URL(request.url).searchParams)
                    return [200, []]
                },
                '/api/projects/:team_id/signals/scout/configs/': () => [200, []],
            },
            post: {
                [NOTES_URL]: async ({ request }) => {
                    const body = (await request.json()) as Record<string, unknown>
                    createdBodies.push(body)
                    return [201, { id: 'note-1', origin: 'human', ...body }]
                },
            },
        })
        initKeaTests()
        logic = reportNotesLogic({ reportId: REPORT_ID, reportScoutName: REPORT_SCOUT })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('finds notes by the report id they quote, across every scout', async () => {
        await expectLogic(logic).toFinishAllListeners()

        // A `skill_name` here would hide notes the report's dismissals and ratings sent to other scouts.
        expect(listQueries[0].get('text')).toEqual(REPORT_ID)
        expect(listQueries[0].has('skill_name')).toBe(false)
    })

    it.each([
        { target: REPORT_SCOUT, expectedSkillName: REPORT_SCOUT },
        { target: EVERY_SCOUT, expectedSkillName: undefined },
    ])('leaves a note for $target that quotes the report id', async ({ target, expectedSkillName }) => {
        await logic.asyncActions.createNote('Focus on the new checkout flow', target)

        expect(createdBodies).toHaveLength(1)
        expect(createdBodies[0].skill_name).toEqual(expectedSkillName)
        expect(createdBodies[0].content).toContain(REPORT_ID)
        expect(createdBodies[0].content).toContain('Focus on the new checkout flow')
        expect(logic.values.lastSaveFailed).toBe(false)
    })
})
