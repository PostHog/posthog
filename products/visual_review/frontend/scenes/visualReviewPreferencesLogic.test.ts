import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { visualReviewPreferencesLogic } from './visualReviewPreferencesLogic'

describe('visualReviewPreferencesLogic', () => {
    let logic: ReturnType<typeof visualReviewPreferencesLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = visualReviewPreferencesLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('defaults adding snapshot images to the comment to off so it is opt-in', async () => {
        await expectLogic(logic).toMatchValues({ addImagesToComment: false })
    })

    it.each([true, false])('remembers the addImagesToComment choice (%s)', async (enabled) => {
        await expectLogic(logic, () => {
            logic.actions.setAddImagesToComment(enabled)
        }).toMatchValues({ addImagesToComment: enabled })
    })
})
