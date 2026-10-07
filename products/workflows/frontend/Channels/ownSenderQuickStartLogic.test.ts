import { expectLogic } from 'kea-test-utils'

import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { IntegrationConfigApi } from 'products/integrations/frontend/generated/api.schemas'

import { ownSenderQuickStartLogic } from './ownSenderQuickStartLogic'

const OWN_SENDER = {
    id: 5,
    kind: 'email',
    display_name: 'Sender <sender@example.com>',
    config: { verified: true, email: 'sender@example.com' },
} satisfies Partial<IntegrationConfigApi>

const UNVERIFIED_OWN_SENDER = { ...OWN_SENDER, config: { verified: false, email: 'sender@example.com' } }

const SANDBOX_SENDER = {
    id: 7,
    kind: 'email',
    display_name: 'Example via PostHog <sandbox@example.com>',
    config: { provider: 'sandbox', verified: true, email: 'sandbox@example.com' },
} satisfies Partial<IntegrationConfigApi>

describe('ownSenderQuickStartLogic', () => {
    let completedSetupTasks: string[]

    beforeEach(() => {
        completedSetupTasks = []
    })

    it.each([
        { case: 'a verified own sender', integrations: [OWN_SENDER], firstRun: true, completes: true },
        { case: 'an unverified own sender', integrations: [UNVERIFIED_OWN_SENDER], firstRun: true, completes: false },
        { case: 'only the sandbox sender', integrations: [SANDBOX_SENDER], firstRun: true, completes: false },
        { case: 'the first run flag off', integrations: [OWN_SENDER], firstRun: false, completes: false },
    ])(
        'completes the own domain quick start task when the loaded senders hold $case: $completes',
        async ({ integrations, firstRun, completes }) => {
            useMocks({
                get: { '/api/projects/:team_id/integrations/': () => [200, { results: integrations }] },
                patch: {
                    '/api/projects/:team_id/': async ({ request }) => {
                        const { onboarding_tasks } = (await request.json()) as {
                            onboarding_tasks: Record<string, string>
                        }
                        completedSetupTasks = Object.keys(onboarding_tasks).filter(
                            (taskId) => onboarding_tasks[taskId] === 'completed'
                        )
                        return [200, {}]
                    },
                },
            })
            initKeaTests()
            globalSetupLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN]: firstRun })

            const logic = ownSenderQuickStartLogic()
            logic.mount()
            await expectLogic(integrationsLogic).toDispatchActions(['loadIntegrationsSuccess'])
            await expectLogic(logic).toFinishAllListeners()

            expect(completedSetupTasks.includes(SetupTaskId.SendFromOwnEmailDomain)).toBe(completes)
        }
    )
})
