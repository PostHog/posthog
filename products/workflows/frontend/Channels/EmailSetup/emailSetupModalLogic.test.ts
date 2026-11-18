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

    it('saves a new sender with the MAIL FROM subdomain the server stored, not the one typed', async () => {
        const createdConfig = {
            email: 'second@example.com',
            name: 'Second',
            provider: 'ses',
            domain: 'example.com',
            mail_from_subdomain: 'bounces',
            reply_to: '',
        }
        const savedBodies: any[] = []
        useMocks({
            post: {
                '/api/projects/:team_id/integrations': () => [
                    201,
                    { id: 7, kind: 'email', config: createdConfig } as IntegrationType,
                ],
                '/api/projects/:team_id/integrations/:id/email/verify': { status: 'pending', dnsRecords: [] },
            },
            patch: {
                '/api/projects/:team_id/integrations/:id/email': async ({ request }) => {
                    savedBodies.push(await request.json())
                    return [200, { id: 7, kind: 'email', config: createdConfig } as IntegrationType]
                },
            },
        })
        const logic = emailSetupModalLogic({ integration: null, onComplete: () => {}, onClose: () => {} })
        logic.mount()

        logic.actions.setEmailSenderValues({ email: 'second@example.com', name: 'Second', mail_from_subdomain: 'own' })
        await expectLogic(logic, () => logic.actions.submitEmailSender()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.submitEmailSender()).toFinishAllListeners()

        expect(savedBodies).toEqual([{ config: expect.objectContaining({ mail_from_subdomain: 'bounces' }) }])
    })
})
