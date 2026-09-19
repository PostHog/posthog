import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { userInterviewTopicsList } from './generated/api'
import { userInterviewsLogic } from './userInterviewsLogic'

jest.mock('./generated/api', () => ({
    userInterviewTopicsList: jest.fn(),
    userInterviewsSearchCreate: jest.fn(),
}))

const mockUserInterviewTopicsList = userInterviewTopicsList as jest.MockedFunction<typeof userInterviewTopicsList>

// The scene is reachable by direct link, bookmark, or the /user_interviews redirect. Every user
// research endpoint answers 403 without the flag, and a load failure is reported as an exception,
// so a flag-off mount must send no request at all.
describe('userInterviewsLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        mockUserInterviewTopicsList.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
        featureFlagLogic.mount()
    })

    it.each([
        ['off', false],
        ['on', true],
    ])('with the user-interviews flag %s, requests topics on mount: %s', async (_state, enabled) => {
        if (enabled) {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.USER_INTERVIEWS], {
                [FEATURE_FLAGS.USER_INTERVIEWS]: true,
            })
        }

        const logic = userInterviewsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockUserInterviewTopicsList).toHaveBeenCalledTimes(enabled ? 1 : 0)
    })
})
