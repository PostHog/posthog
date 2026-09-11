import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { FREE_TRIAL_PR_DISABLED_REASON, inboxTaskKickoffLogic } from './inboxTaskKickoffLogic'

describe('inboxTaskKickoffLogic', () => {
    describe('freeTrialDisabledReason', () => {
        let logic: ReturnType<typeof inboxTaskKickoffLogic.build>

        beforeEach(() => {
            // featureFlagLogic persists to localStorage, which jsdom keeps across tests.
            localStorage.clear()
            initKeaTests()
            featureFlagLogic.mount()
            logic = inboxTaskKickoffLogic()
            logic.mount()
        })

        afterEach(() => {
            logic.unmount()
        })

        it.each([
            [true, FREE_TRIAL_PR_DISABLED_REASON],
            [false, null],
        ])('with the free trial flag %s, Create PR carries %s', (enabled, expected) => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SELF_DRIVING_FREE_TRIAL], {
                [FEATURE_FLAGS.SELF_DRIVING_FREE_TRIAL]: enabled,
            })
            expect(logic.values.freeTrialDisabledReason).toBe(expected)
        })
    })
})
