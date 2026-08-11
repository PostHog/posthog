import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { agentSetupModalLogic } from './agentSetupModalLogic'

describe('agentSetupModalLogic', () => {
    let logic: ReturnType<typeof agentSetupModalLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('restores the GitHub modal from the callback URL and only removes GitHub parameters when closed', () => {
        router.actions.push('/inbox/config', {
            setup: 'github',
            integration_id: '12',
            installation_id: '34',
            github_setup_error: 'pending',
            error_message: 'Try again',
            github_install_pending: '1',
            source: 'saved-filter',
        })
        const callbackPath = router.values.location.pathname

        logic = agentSetupModalLogic()
        logic.mount()

        expect(logic.values.openModal).toBe('github')

        logic.actions.closeSetupModal()

        expect(router.values.location.pathname).toBe(callbackPath)
        expect(router.values.searchParams).toEqual({ source: 'saved-filter' })
    })
})
