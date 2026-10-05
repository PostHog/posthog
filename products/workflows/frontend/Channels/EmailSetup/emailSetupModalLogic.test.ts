import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import { emailSetupModalLogic } from './emailSetupModalLogic'

describe('emailSetupModalLogic', () => {
    beforeEach(() => {
        useMocks({
            get: { '/api/environments/:team_id/integrations': { results: [] } },
            post: {
                '/api/environments/:team_id/integrations/:id/email/verify': { status: 'pending', dnsRecords: [] },
            },
        })
        initKeaTests()
    })

    // A legacy or hand-edited integration row can hold a config without an `email` key. An unguarded
    // read of it threw, and the error escaped to the app error boundary, so the whole scene went
    // blank instead of the modal opening.
    it('keeps the form defaults when the integration config has no email', async () => {
        const logic = emailSetupModalLogic({
            integration: { id: 1, kind: 'email', config: {} } as IntegrationType,
            onComplete: () => {},
            onClose: () => {},
        })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            domain: '',
            emailSender: expect.objectContaining({ email: '', name: '', provider: 'ses' }),
        })
    })

    const EMAIL_CONFIG_URL = '/api/environments/:team_id/integrations/:id/email/'

    const VERIFY_URL = '/api/environments/:team_id/integrations/:id/email/verify'

    const mountWithSavedSender = async (): Promise<{
        logic: ReturnType<typeof emailSetupModalLogic.build>
        onComplete: jest.Mock
        onClose: jest.Mock
    }> => {
        const onComplete = jest.fn()
        const onClose = jest.fn()
        const logic = emailSetupModalLogic({
            integration: {
                id: 7,
                kind: 'email',
                config: { email: 'hello@example.com', name: 'Hello', domain: 'example.com' },
            } as IntegrationType,
            onComplete,
            onClose,
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['verifyDomainSuccess'])
        return { logic, onComplete, onClose }
    }

    it.each([
        ['pending', 'onClose'],
        ['success', 'onComplete'],
    ])('saving with a %s domain verification calls %s with the saved sender', async (status, callback) => {
        useMocks({
            post: { [VERIFY_URL]: { status, dnsRecords: [] } },
            patch: { [EMAIL_CONFIG_URL]: { id: 7, kind: 'email', config: { email: 'hello@example.com' } } },
        })
        const { logic, onComplete, onClose } = await mountWithSavedSender()

        await expectLogic(logic, () => logic.actions.saveAndFinish()).toDispatchActions(['submitEmailSenderSuccess'])

        const called = { onClose, onComplete }[callback]
        const notCalled = callback === 'onClose' ? onComplete : onClose
        expect(called).toHaveBeenCalledWith(7)
        expect(notCalled).not.toHaveBeenCalled()
    })

    it('keeps the modal open when saving fails', async () => {
        useMocks({
            post: { [VERIFY_URL]: { status: 'success', dnsRecords: [] } },
            patch: { [EMAIL_CONFIG_URL]: () => [400, { detail: 'Invalid sender' }] },
        })
        const { logic, onComplete, onClose } = await mountWithSavedSender()

        await expectLogic(logic, () => logic.actions.saveAndFinish()).toDispatchActions(['submitEmailSenderFailure'])

        expect(onComplete).not.toHaveBeenCalled()
        expect(onClose).not.toHaveBeenCalled()
    })
})
