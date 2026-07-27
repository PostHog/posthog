import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { messageTemplateLogic } from './messageTemplateLogic'

describe('messageTemplateLogic unsaved-changes guard', () => {
    let logic: ReturnType<typeof messageTemplateLogic.build>
    let confirmSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        // window.confirm is the boundary kea-router calls to block in-app navigation.
        confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true)
        logic = messageTemplateLogic({ id: 'new' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        confirmSpy.mockRestore()
    })

    it.each([
        { description: 'blocks navigation away from an unsaved new template', changed: true, expectedCalls: 1 },
        {
            description: 'does not block navigation when there are no unsaved changes',
            changed: false,
            expectedCalls: 0,
        },
    ])('$description', async ({ changed, expectedCalls }) => {
        if (changed) {
            logic.actions.setTemplateValue('name', 'My one-hour template')
            await expectLogic(logic).toMatchValues({ templateChanged: true })
        } else {
            await expectLogic(logic).toMatchValues({ templateChanged: false })
        }

        router.actions.push('/workflows/library')

        expect(confirmSpy).toHaveBeenCalledTimes(expectedCalls)
    })
})
