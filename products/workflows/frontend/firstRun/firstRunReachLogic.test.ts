import { expectLogic } from 'kea-test-utils'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { IntegrationConfigApi } from 'products/integrations/frontend/generated/api.schemas'

import type { EmailReachApi } from '../generated/api.schemas'
import { firstRunReachLogic } from './firstRunReachLogic'

const SANDBOX_SENDER = {
    id: 7,
    kind: 'email',
    display_name: 'Example via PostHog <sandbox@example.com>',
    config: { provider: 'sandbox', verified: true, email: 'sandbox@example.com' },
} satisfies Partial<IntegrationConfigApi>

const OWN_SENDER = {
    id: 5,
    kind: 'email',
    display_name: 'Sender <sender@example.com>',
    config: { verified: true, email: 'sender@example.com' },
} satisfies Partial<IntegrationConfigApi>

const EMAIL_REACH: EmailReachApi = {
    verified_member_count: 3,
    project_email_count: 1240,
    email_senders: [],
}

describe('firstRunReachLogic', () => {
    let logic: ReturnType<typeof firstRunReachLogic.build>
    let integrations: Partial<IntegrationConfigApi>[]

    beforeEach(() => {
        integrations = [SANDBOX_SENDER]
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': () => [200, { results: integrations }],
                '/api/projects/:team_id/hog_flows/email_reach/': () => [200, EMAIL_REACH],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    async function mountFor(senderIntegrationId: number | null): Promise<void> {
        logic = firstRunReachLogic({ senderIntegrationId })
        logic.mount()
        await expectLogic(integrationsLogic).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()
    }

    it('says who the sandbox sender reaches, with both counts from the reach endpoint', async () => {
        await mountFor(SANDBOX_SENDER.id)

        expect(logic.values.reach).toEqual({
            senderAddress: 'sandbox@example.com',
            counts: { reached: 3, notReachedYet: 1240 },
            ownDomain: 'none',
        })
    })

    it('keeps the sender line without counts when the reach endpoint refuses', async () => {
        useMocks({
            get: { '/api/projects/:team_id/hog_flows/email_reach/': () => [403, { detail: 'Permission denied' }] },
        })
        await mountFor(SANDBOX_SENDER.id)

        expect(logic.values.reach).toEqual({ senderAddress: 'sandbox@example.com', counts: null, ownDomain: 'none' })
    })

    it('says the own domain is verifying while the own sender is not verified yet', async () => {
        integrations = [SANDBOX_SENDER, { ...OWN_SENDER, config: { verified: false, email: 'sender@example.com' } }]
        await mountFor(SANDBOX_SENDER.id)

        expect(logic.values.reach).toEqual(expect.objectContaining({ ownDomain: 'verifying' }))
    })

    it.each([
        ['the workflow still sends from the sandbox sender', SANDBOX_SENDER.id],
        ['the workflow sends from the own sender', OWN_SENDER.id],
    ])('says nothing once the own domain is verified and %s', async (_, senderIntegrationId) => {
        integrations = [SANDBOX_SENDER, OWN_SENDER]
        await mountFor(senderIntegrationId)

        expect(logic.values.reach).toBeNull()
    })
})
