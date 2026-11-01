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

    it.each([
        ['leaves out an unchanged MAIL FROM label', {}, undefined],
        ['sends an edited MAIL FROM label', { mail_from_subdomain: 'bounce' }, 'bounce'],
    ])('%s when saving a sender', async (_, edit, expectedLabel) => {
        const updates: Record<string, any>[] = []
        useMocks({
            get: { '/api/environments/:team_id/integrations': { results: [] } },
            patch: {
                '/api/environments/:team_id/integrations/:id/email': async ({ request }) => {
                    const body = (await request.json()) as { config: Record<string, any> }
                    updates.push(body.config)
                    return [200, { id: 1, kind: 'email', config: body.config }]
                },
            },
            post: {
                '/api/environments/:team_id/integrations/:id/email/verify': { status: 'pending', dnsRecords: [] },
            },
        })
        const logic = emailSetupModalLogic({
            integration: {
                id: 1,
                kind: 'email',
                config: { email: 'hello@example.com', name: 'Hello', provider: 'ses', mail_from_subdomain: 'feedback' },
            } as IntegrationType,
            onComplete: () => {},
            onClose: () => {},
        })
        logic.mount()

        logic.actions.setEmailSenderValues({ name: 'Renamed', ...edit })
        await expectLogic(logic, () => logic.actions.submitEmailSender()).toFinishAllListeners()

        expect(updates).toHaveLength(1)
        expect(updates[0].mail_from_subdomain).toBe(expectedLabel)
    })
})
