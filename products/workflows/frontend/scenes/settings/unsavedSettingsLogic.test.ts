import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'

import { initKeaTests } from '~/test/init'

import { unsavedSettingsLogic } from './unsavedSettingsLogic'

describe('unsavedSettingsLogic', () => {
    let logic: ReturnType<typeof unsavedSettingsLogic.build>
    const confirm = jest.fn()

    beforeEach(() => {
        initKeaTests()
        window.confirm = confirm
        confirm.mockReset()
        logic = unsavedSettingsLogic({ sectionId: 'test-section', message: 'Leave without saving?' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    async function navigate(): Promise<void> {
        router.actions.push('/elsewhere')
        await expectLogic(router).toFinishAllListeners()
    }

    it('lets navigation through when nothing is unsaved', async () => {
        await navigate()

        expect(confirm).not.toHaveBeenCalled()
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual('/elsewhere')
    })

    it('keeps the person on the page when they cancel the prompt', async () => {
        confirm.mockReturnValue(false)
        logic.actions.setHasUnsavedChanges(true)

        await navigate()

        expect(confirm).toHaveBeenCalledWith('Leave without saving?')
        expect(removeProjectIdIfPresent(router.values.location.pathname)).not.toEqual('/elsewhere')
        expect(logic.values.hasUnsavedChanges).toBe(true)
    })

    it('stays quiet when only the hash changes', async () => {
        confirm.mockReturnValue(false)
        logic.actions.setHasUnsavedChanges(true)

        router.actions.push(`${router.values.location.pathname}#a-heading`)
        await expectLogic(router).toFinishAllListeners()

        expect(confirm).not.toHaveBeenCalled()
        expect(logic.values.hasUnsavedChanges).toBe(true)
    })

    it('navigates and disarms when they confirm', async () => {
        confirm.mockReturnValue(true)
        logic.actions.setHasUnsavedChanges(true)

        await navigate()

        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual('/elsewhere')
        expect(logic.values.hasUnsavedChanges).toBe(false)
    })
})
