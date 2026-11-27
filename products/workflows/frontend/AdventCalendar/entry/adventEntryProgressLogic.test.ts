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

        const logic = adventEntryProgressLogic()
        logic.mount()

        expect(logic.values.progress?.opened ?? null).toEqual(opened)
        logic.unmount()
    })
})
