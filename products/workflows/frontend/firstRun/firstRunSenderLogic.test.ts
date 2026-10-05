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

const SANDBOX_SENDER = {
    id: 7,
    kind: 'email',
    display_name: 'Example via PostHog <sandbox@example.com>',
    config: { provider: 'sandbox', verified: true, email: 'sandbox@example.com' },
} satisfies Partial<IntegrationConfigApi>

describe('firstRunSenderLogic', () => {
    let logic: ReturnType<typeof firstRunSenderLogic.build>
    let integrations: Partial<IntegrationConfigApi>[]
    let ensureCalls: number

    beforeEach(() => {
        integrations = []
        ensureCalls = 0
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': () => [200, { results: integrations }],
            },
            post: {
                '/api/projects/:team_id/integrations/email_sandbox_sender/': () => {
                    ensureCalls += 1
                    integrations = [...integrations, SANDBOX_SENDER]
                    return [200, SANDBOX_SENDER]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER], {
            [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER]: true,
        })
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('uses the first verified own sender without ensuring a sandbox sender', async () => {
        integrations = [
            { id: 3, kind: 'slack', config: { verified: true } },
            { id: 4, kind: 'email', config: { verified: false } },
            SANDBOX_SENDER,
            OWN_SENDER,
            { ...OWN_SENDER, id: 6 },
        ]
        logic = firstRunSenderLogic()
        logic.mount()

        await expectLogic(integrationsLogic).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({ firstRunSender: expect.objectContaining(OWN_SENDER) })
        expect(ensureCalls).toBe(0)
    })

    it('ensures the sandbox sender once when there is no verified own sender', async () => {
        integrations = [{ ...OWN_SENDER, config: { verified: false } }]
        logic = firstRunSenderLogic()
        logic.mount()

        await expectLogic(integrationsLogic).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({ firstRunSender: expect.objectContaining(SANDBOX_SENDER) })
        expect(ensureCalls).toBe(1)

        await expectLogic(integrationsLogic, () => {
            integrationsLogic.actions.loadIntegrations()
            integrationsLogic.actions.loadIntegrations()
        }).toFinishAllListeners()
        expect(logic.values.firstRunSender).toEqual(expect.objectContaining(SANDBOX_SENDER))
        expect(ensureCalls).toBe(1)
    })

    it('returns none when the ensure endpoint returns 404 and does not retry on reload', async () => {
        useMocks({
            post: {
                '/api/projects/:team_id/integrations/email_sandbox_sender/': () => {
                    ensureCalls += 1
                    return [404, { detail: 'Not found.' }]
                },
            },
        })
        logic = firstRunSenderLogic()
        logic.mount()

        await expectLogic(integrationsLogic).toFinishAllListeners()
        expect(logic.values.firstRunSender).toBeNull()
        expect(ensureCalls).toBe(1)

        await expectLogic(integrationsLogic, () => {
            integrationsLogic.actions.loadIntegrations()
        }).toFinishAllListeners()
        expect(logic.values.firstRunSender).toBeNull()
        expect(ensureCalls).toBe(1)
    })

    it.each([
        { integrations: [SANDBOX_SENDER], expected: null },
        { integrations: [SANDBOX_SENDER, OWN_SENDER], expected: expect.objectContaining(OWN_SENDER) },
    ])('ignores the sandbox sender while its flag is off', async ({ integrations: initialIntegrations, expected }) => {
        integrations = initialIntegrations
        featureFlagLogic.actions.setFeatureFlags([], {})
        logic = firstRunSenderLogic()
        logic.mount()

        await expectLogic(integrationsLogic).toFinishAllListeners()
        expect(logic.values.firstRunSender).toEqual(expected)
        expect(ensureCalls).toBe(0)
    })

    it('resolves the sandbox sender when the flag arrives after integrations', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        logic = firstRunSenderLogic()
        logic.mount()
        await expectLogic(integrationsLogic).toFinishAllListeners()
        expect(logic.values.firstRunSender).toBeNull()
        expect(ensureCalls).toBe(0)

        await expectLogic(integrationsLogic, () => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER], {
                [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER]: true,
            })
        }).toFinishAllListeners()
        expect(logic.values.firstRunSender).toEqual(expect.objectContaining(SANDBOX_SENDER))
        expect(ensureCalls).toBe(1)
    })
})
