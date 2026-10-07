import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ActivationTaskStatus, TeamType } from '~/types'

import { broadcastTestSendLogic } from './Broadcasts/broadcastTestSendLogic'
import { messageTemplateLogic } from './TemplateLibrary/messageTemplateLogic'
import { messageTemplateTestSendLogic } from './TemplateLibrary/messageTemplateTestSendLogic'
import { hogFlowEditorNotificationTestLogic } from './Workflows/hogflows/panel/testing/hogFlowEditorNotificationTestLogic'
import type { HogFlowAction } from './Workflows/hogflows/types'
import { NEW_WORKFLOW, workflowLogic } from './Workflows/workflowLogic'

const EMAIL_ACTION: HogFlowAction = {
    id: 'email_node',
    type: 'function_email',
    name: 'Welcome email',
    description: '',
    created_at: 0,
    updated_at: 0,
    config: {
        template_id: 'template-email',
        inputs: {
            email: {
                value: {
                    from: { integrationId: 5 },
                    to: { email: 'tester@example.com', name: '' },
                    subject: 'Welcome',
                    text: 'Hello',
                },
            },
        },
    },
}

async function sendTestEmail(
    surface: 'template' | 'broadcast' | 'email step',
    { mocked = false, actionId = 'email_node' }: { mocked?: boolean; actionId?: string } = {}
): Promise<void> {
    if (surface === 'email step') {
        const workflow = workflowLogic({ id: 'new' })
        workflow.mount()
        await expectLogic(workflow).toFinishAllListeners()
        workflow.actions.setWorkflowValues({ actions: [...NEW_WORKFLOW.actions, EMAIL_ACTION] })
        const logic = hogFlowEditorNotificationTestLogic({ id: 'new' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setSelectedNodeId(actionId)
        logic.actions.setTestInvocationValues({
            globals: JSON.stringify({ person: { properties: { email: 'tester@example.com' } } }),
            mock_async_functions: mocked,
        })
        await expectLogic(logic, () => logic.actions.submitTestInvocation()).toFinishAllListeners()
        return
    }
    if (surface === 'template') {
        const template = messageTemplateLogic({ id: 'new' })
        template.mount()
        template.actions.setTemplateValue('content.email.subject', 'Welcome')
        template.actions.setTemplateValue('content.email.text', 'Hello')
    }
    const logic =
        surface === 'template' ? messageTemplateTestSendLogic({ id: 'new' }) : broadcastTestSendLogic({ id: 'new' })
    logic.mount()
    logic.actions.setRecipientEmail('tester@example.com')
    await expectLogic(logic, () => logic.actions.sendTestEmail()).toFinishAllListeners()
}

describe('test email quick start completion', () => {
    let persistedTasks: Record<string, string>
    let invocationCount: number
    beforeEach(() => {
        localStorage.clear()
        persistedTasks = {}
        invocationCount = 0
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': { results: [] },
                '/api/environments/:team_id/persons/': { results: [] },
            },
            patch: {
                '/api/environments/:team_id/': async ({ request }) => {
                    const body = (await request.json()) as Pick<TeamType, 'onboarding_tasks'>
                    persistedTasks = body.onboarding_tasks ?? {}
                    return [200, { ...MOCK_DEFAULT_TEAM, ...body }]
                },
            },
        })
        initKeaTests()
        globalSetupLogic.mount()
    })

    describe.each(['template', 'broadcast', 'email step'] as const)('%s', (surface) => {
        it.each([
            { outcome: 'delivered', status: 'success', logs: [], httpStatus: 200, completed: true },
            {
                outcome: 'delivered with first run disabled',
                status: 'success',
                logs: [],
                httpStatus: 200,
                completed: false,
                firstRun: false,
            },
            { outcome: 'skipped', status: 'skipped', logs: [], httpStatus: 200, completed: false },
            {
                outcome: 'declined by the email worker',
                status: 'success',
                logs: [
                    {
                        level: 'info',
                        message: 'Skipping send: recipient has opted out.',
                        timestamp: '2026-01-01T00:00:00Z',
                    },
                ],
                httpStatus: 200,
                completed: false,
            },
            { outcome: 'failed', status: 'error', logs: [], httpStatus: 200, completed: false },
            { outcome: 'rejected by the API', status: 'error', logs: [], httpStatus: 500, completed: false },
        ])(
            'completes the quick start task only when the test email is delivered: $outcome',
            async ({ status, logs, httpStatus, completed, firstRun = true }) => {
                featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN]: firstRun })
                useMocks({
                    post: {
                        '/api/environments/:team_id/hog_flows/:id/invocations/': () => {
                            invocationCount++
                            return [httpStatus, { status, nextActionId: null, logs }]
                        },
                    },
                })

                await sendTestEmail(surface)
                await expectLogic(teamLogic).toFinishAllListeners()

                expect(invocationCount).toBe(1)
                expect(globalSetupLogic.values.optimisticTaskStatuses[SetupTaskId.SendWorkflowTestEmail]).toBe(
                    completed ? ActivationTaskStatus.COMPLETED : undefined
                )
                expect(persistedTasks[SetupTaskId.SendWorkflowTestEmail]).toBe(
                    completed ? ActivationTaskStatus.COMPLETED : undefined
                )
            }
        )
    })

    it.each([
        { run: 'a mocked email', mocked: true, actionId: 'email_node' },
        { run: 'a non-email step', mocked: false, actionId: 'exit_node' },
    ])('leaves the task incomplete after $run succeeds', async ({ mocked, actionId }) => {
        useMocks({
            post: {
                '/api/environments/:team_id/hog_flows/:id/invocations/': () => {
                    invocationCount++
                    return [200, { status: 'success', nextActionId: null, logs: [] }]
                },
            },
        })

        await sendTestEmail('email step', { mocked, actionId })

        expect(invocationCount).toBe(1)
        expect(globalSetupLogic.values.optimisticTaskStatuses[SetupTaskId.SendWorkflowTestEmail]).toBeUndefined()
        expect(persistedTasks[SetupTaskId.SendWorkflowTestEmail]).toBeUndefined()
    })
})
