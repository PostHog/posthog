import { expectLogic } from 'kea-test-utils'

import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import { emailSetupModalLogic } from './emailSetupModalLogic'

describe('emailSetupModalLogic', () => {
    let verificationStatus: string
    let completedSetupTasks: string[]

    beforeEach(() => {
        verificationStatus = 'pending'
        completedSetupTasks = []
        useMocks({
            get: { '/api/environments/:team_id/integrations': { results: [] } },
            post: {
                '/api/environments/:team_id/integrations/:id/email/verify': () => [
                    200,
                    { status: verificationStatus, dnsRecords: [] },
                ],
            },
            patch: {
                '/api/projects/:team_id/': async ({ request }) => {
                    const { onboarding_tasks } = (await request.json()) as { onboarding_tasks: Record<string, string> }
                    completedSetupTasks = Object.keys(onboarding_tasks).filter(
                        (taskId) => onboarding_tasks[taskId] === 'completed'
                    )
                    return [200, {}]
                },
            },
        })
        initKeaTests()
        globalSetupLogic.mount()
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
        { status: 'success', firstRun: true, completesOwnDomainTask: true },
        { status: 'pending', firstRun: true, completesOwnDomainTask: false },
        { status: 'success', firstRun: false, completesOwnDomainTask: false },
    ])(
        'completes the own domain quick start task only when verification returns $status',
        async ({ status, firstRun, completesOwnDomainTask }) => {
            verificationStatus = status
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN]: firstRun })
            const logic = emailSetupModalLogic({
                integration: { id: 1, kind: 'email', config: { email: 'hello@example.com' } } as IntegrationType,
                onComplete: () => {},
                onClose: () => {},
            })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            expect(completedSetupTasks.includes(SetupTaskId.SendFromOwnEmailDomain)).toBe(completesOwnDomainTask)
        }
    )
})
