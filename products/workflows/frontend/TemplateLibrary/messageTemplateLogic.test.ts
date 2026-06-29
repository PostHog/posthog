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

    it('blocks navigation away from an unsaved new template', async () => {
        logic.actions.setTemplateValue('name', 'My one-hour template')
        await expectLogic(logic).toMatchValues({ templateChanged: true })

        router.actions.push('/workflows/library')

        expect(confirmSpy).toHaveBeenCalledTimes(1)
    })

    it('does not block navigation when there are no unsaved changes', async () => {
        await expectLogic(logic).toMatchValues({ templateChanged: false })

        router.actions.push('/workflows/library')

        expect(confirmSpy).not.toHaveBeenCalled()
    })
})
