import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { IntegrationConfigApi } from 'products/integrations/frontend/generated/api.schemas'

import { firstRunSenderLogic } from './firstRunSenderLogic'

const OWN_SENDER = {
    id: 5,
    kind: 'email',
    display_name: 'Sender <sender@example.com>',
    config: { verified: true, email: 'sender@example.com' },
} satisfies Partial<IntegrationConfigApi>

describe('firstRunSenderLogic', () => {
    let logic: ReturnType<typeof firstRunSenderLogic.build>
    let integrations: Partial<IntegrationConfigApi>[]

    beforeEach(() => {
        integrations = []
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': () => [200, { results: integrations }],
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN]: true })
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('uses the first verified own email sender from the existing integrations list', async () => {
        integrations = [
            { id: 3, kind: 'slack', config: { verified: true } },
            { ...OWN_SENDER, id: 4, config: { verified: false } },
            { ...OWN_SENDER, id: 7, config: { provider: 'sandbox', verified: true } },
            OWN_SENDER,
            { ...OWN_SENDER, id: 6 },
        ]
        logic = firstRunSenderLogic()
        logic.mount()

        await expectLogic(integrationsLogic).toFinishAllListeners()
        expect(logic.values.firstRunSender).toEqual(expect.objectContaining(OWN_SENDER))

        featureFlagLogic.actions.setFeatureFlags([], {})
        expect(logic.values.firstRunSender).toBeNull()
        expect(logic.values.firstRunSenderLoading).toBe(false)
    })

    it.each([
        { initialIntegrations: [] },
        { initialIntegrations: [{ ...OWN_SENDER, config: { verified: false } }] },
        { initialIntegrations: [{ ...OWN_SENDER, config: { provider: 'sandbox', verified: true } }] },
    ])('requires a verified own email sender', async ({ initialIntegrations }) => {
        integrations = initialIntegrations
        logic = firstRunSenderLogic()
        logic.mount()

        await expectLogic(integrationsLogic).toFinishAllListeners()
        expect(logic.values.firstRunSender).toBeNull()
    })
})
