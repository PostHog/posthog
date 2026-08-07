import { expectLogic } from 'kea-test-utils'

import api, { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import { emailSetupModalLogic } from './emailSetupModalLogic'

const SAVED_INTEGRATION = {
    id: 42,
    kind: 'email',
    config: { email: 'sender@example.com', domain: 'example.com' },
} as unknown as IntegrationType

describe('emailSetupModalLogic', () => {
    let logic: ReturnType<typeof emailSetupModalLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api.integrations, 'list').mockResolvedValue({ results: [] } as any)
        jest.spyOn(lemonToast, 'error').mockReturnValue('' as any)
        logic = emailSetupModalLogic({ onComplete: jest.fn(), onClose: jest.fn() })
        logic.mount()
        logic.actions.setSavedIntegration(SAVED_INTEGRATION)
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    describe('verifyDomain error handling', () => {
        // Guards the silent dead-end: a stale integration id returns 404 and the Verify button used to
        // swallow the error, leaving the modal pointing at a sender that no longer exists.
        it('drops back to the setup form and warns on a 404', async () => {
            jest.spyOn(api.integrations, 'verifyEmail').mockRejectedValue(new ApiError('Not found', 404))

            await expectLogic(logic, () => {
                logic.actions.verifyDomain()
            }).toDispatchActions(['verifyDomainSuccess'])

            expect(logic.values.savedIntegration).toBeNull()
            expect(lemonToast.error).toHaveBeenCalled()
        })

        it('keeps the saved integration on a non-404 failure', async () => {
            jest.spyOn(api.integrations, 'verifyEmail').mockRejectedValue(new ApiError('Server error', 500))

            await expectLogic(logic, () => {
                logic.actions.verifyDomain()
            }).toDispatchActions(['verifyDomainSuccess'])

            expect(logic.values.savedIntegration).toEqual(SAVED_INTEGRATION)
            expect(lemonToast.error).toHaveBeenCalled()
        })
    })
})
