import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import { emailSetupModalLogic } from './emailSetupModalLogic'

const SENDER = {
    id: 1,
    kind: 'email',
    config: { email: 'hello@example.com', name: 'Hello', domain: 'example.com', provider: 'ses' },
} as IntegrationType

describe('emailSetupModalLogic', () => {
    let verifyStatus: 'success' | 'pending'

    beforeEach(() => {
        verifyStatus = 'pending'
        useMocks({
            get: { '/api/environments/:team_id/integrations': { results: [] } },
            post: {
                '/api/environments/:team_id/integrations/:id/email/verify': () => [
                    200,
                    { status: verifyStatus, dnsRecords: [] },
                ],
            },
            patch: { '/api/environments/:team_id/integrations/:id/email': SENDER },
        })
        initKeaTests()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    // A legacy or hand-edited integration row can hold a config without an `email` key. An unguarded
    // read of it threw, and the error escaped to the app error boundary, so the whole scene went
    // blank instead of the modal opening.
    it('keeps the form defaults when the integration config has no email', async () => {
        const logic = emailSetupModalLogic({
            integration: { id: 1, kind: 'email', config: {} } as IntegrationType,
            surface: 'channels',
            onComplete: () => {},
            onClose: () => {},
        })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            domain: '',
            emailSender: expect.objectContaining({ email: '', name: '', provider: 'ses' }),
        })
    })

    it.each([
        { scenario: 'a new sender', integration: null, verifyStatus: 'pending', furthestStep: 'details' },
        { scenario: 'an unverified sender', integration: SENDER, verifyStatus: 'pending', furthestStep: 'dns_records' },
        { scenario: 'a verified sender', integration: SENDER, verifyStatus: 'success', furthestStep: 'verified' },
    ] as const)(
        'reports the furthest step when $scenario is closed early',
        async ({ integration, verifyStatus: status, furthestStep }) => {
            verifyStatus = status
            const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
            const onClose = jest.fn()
            const logic = emailSetupModalLogic({
                integration,
                surface: 'onboarding_wizard',
                onComplete: () => {},
                onClose,
            })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.closeModal()

            expect(capture).toHaveBeenCalledWith('email domain setup closed', {
                furthest_step: furthestStep,
                surface: 'onboarding_wizard',
                completed: false,
            })
            expect(onClose).toHaveBeenCalledWith(integration?.id)
        }
    )

    it('reports a completed setup when the sender is saved', async () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        const onComplete = jest.fn()
        const logic = emailSetupModalLogic({ integration: SENDER, surface: 'channels', onComplete, onClose: () => {} })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.submitEmailSender()
        await expectLogic(logic).toFinishAllListeners()

        expect(capture).toHaveBeenCalledWith('email domain setup closed', {
            furthest_step: 'dns_records',
            surface: 'channels',
            completed: true,
        })
        expect(onComplete).toHaveBeenCalledWith(SENDER.id)
    })
})
