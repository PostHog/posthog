import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { PROGRESS_STORAGE_KEY } from '../adventProgressStorage'
import { adventEntryProgressLogic } from './adventEntryProgressLogic'

describe('adventEntryProgressLogic', () => {
    beforeEach(() => {
        window.localStorage.clear()
        initKeaTests()
    })

    it.each([
        ['is unknown while no user is loaded', null, { [MOCK_DEFAULT_USER.uuid]: { opened: [1] } }, null],
        ['reads the doors this person opened', MOCK_DEFAULT_USER, { [MOCK_DEFAULT_USER.uuid]: { opened: [1] } }, [1]],
        ['is empty when only someone else opened doors', MOCK_DEFAULT_USER, { other: { opened: [1] } }, []],
        ['is empty when the stored progress is unreadable', MOCK_DEFAULT_USER, 'not json', []],
    ])('%s', (_, user, stored, opened) => {
        userLogic.actions.loadUserSuccess(user)
        window.localStorage.setItem(PROGRESS_STORAGE_KEY, typeof stored === 'string' ? stored : JSON.stringify(stored))

        const logic = adventEntryProgressLogic({ today: 3 })
        logic.mount()

        expect(logic.values.progress?.opened ?? null).toEqual(opened)
        logic.unmount()
    })

    it.each([
        ['the first door with nothing opened on December 3', 3, [], {}, 1],
        ["today's door once the doors before it are open", 3, [1, 2], { 2: 'james' }, 3],
        ["no door once today's door is open", 3, [1, 2, 3], { 2: 'james' }, null],
        ['no door before December', 0, [], {}, null],
    ])('points the button at %s', (_, today, opened, answers, nextDoorDay) => {
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        window.localStorage.setItem(
            PROGRESS_STORAGE_KEY,
            JSON.stringify({ [MOCK_DEFAULT_USER.uuid]: { opened, answers } })
        )

        const logic = adventEntryProgressLogic({ today })
        logic.mount()

        expect(logic.values.nextDoorDay).toBe(nextDoorDay)
        logic.unmount()
    })
})
