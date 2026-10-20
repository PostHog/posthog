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

    it('does not open inbox setup from the standalone trials page', () => {
        router.actions.push('/inbox/scout-trials', { setup: 'github' })
        logic = agentSetupModalLogic()
        logic.mount()

        expect(logic.values.openModal).toBeNull()
    })

    it.each(['github', 'signal-sources'] as const)(
        'restores the %s modal from the callback URL and removes callback parameters when closed',
        (setup) => {
            router.actions.push('/inbox/config', {
                setup,
                signal_source: 'intercom',
                integration_error: 'access_denied',
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

            expect(logic.values.openModal).toBe(setup)

            logic.actions.closeSetupModal()

            expect(router.values.location.pathname).toBe(callbackPath)
            expect(router.values.searchParams).toEqual({ source: 'saved-filter' })
        }
    )
})
