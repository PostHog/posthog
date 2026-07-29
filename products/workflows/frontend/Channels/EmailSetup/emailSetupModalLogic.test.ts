import { expectLogic } from 'kea-test-utils'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import { emailSetupModalLogic } from './emailSetupModalLogic'

const emailIntegration = (
    id: number,
    email: string,
    mailFromSubdomain: string,
    createdAt: string
): Partial<IntegrationType> => ({
    id,
    kind: 'email',
    created_at: createdAt,
    display_name: email,
    config: {
        email,
        domain: email.split('@')[1],
        name: 'Existing sender',
        provider: 'ses',
        mail_from_subdomain: mailFromSubdomain,
        verified: true,
    },
})

describe('emailSetupModalLogic', () => {
    let logic: ReturnType<typeof emailSetupModalLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/': () => [
                    200,
                    {
                        results: [
                            emailIntegration(1, 'hello@example.com', 'mail', '2026-01-01T00:00:00Z'),
                            emailIntegration(2, 'sales@example.com', 'mail', '2026-02-01T00:00:00Z'),
                        ],
                    },
                ],
            },
        })
        initKeaTests()
        logic = emailSetupModalLogic({ onComplete: jest.fn(), onClose: jest.fn() })
        logic.mount()
        await expectLogic(integrationsLogic).toFinishAllListeners()
    })

    it('rejects an address that already has a sender instead of overwriting it', async () => {
        logic.actions.setEmailSenderValues({ name: 'New sender', email: 'Hello@example.com' })

        await expectLogic(logic).toMatchValues({
            duplicateSender: expect.objectContaining({ id: 1 }),
            isEmailSenderValid: false,
        })
        expect(logic.values.emailSenderValidationErrors.email).toMatch(/already has a sender/)
    })

    it('inherits the domain-wide MAIL FROM subdomain for a new sender on a known domain', async () => {
        logic.actions.setEmailSenderValue('email', 'support@example.com')

        await expectLogic(logic).toMatchValues({
            duplicateSender: null,
            domainMailFromSubdomain: 'mail',
        })
        expect(logic.values.emailSender.mail_from_subdomain).toEqual('mail')
        expect(logic.values.domainSenders.map((sender) => sender.config.email)).toEqual([
            'hello@example.com',
            'sales@example.com',
        ])
    })
})
