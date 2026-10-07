import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { emailTemplaterLogic } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'
import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { IntegrationConfigApi } from 'products/integrations/frontend/generated/api.schemas'

import type { HogFlowTemplateApi } from '../generated/api.schemas'
import type { HogFlow, HogFlowAction } from '../Workflows/hogflows/types'
import { firstRunMakeItYoursLogic } from './firstRunMakeItYoursLogic'

const SENDER = {
    id: 5,
    kind: 'email',
    display_name: 'Sender <sender@example.com>',
    config: { verified: true, email: 'sender@example.com' },
} satisfies Partial<IntegrationConfigApi>

function emailAction(id: string, subject: string): HogFlowAction {
    return {
        id,
        type: 'function_email',
        name: subject,
        description: '',
        created_at: 0,
        updated_at: 0,
        config: {
            template_id: 'template-email',
            inputs: {
                email: {
                    value: {
                        to: { email: '{{ person.properties.email }}', name: '' },
                        from: { name: '', email: '' },
                        subject,
                        html: `<p>${subject}</p>`,
                        text: subject,
                        design: { body: { rows: [], values: { subject } } },
                    },
                    templating: 'liquid',
                },
            },
        },
    } as HogFlowAction
}

function delayAction(id: string, duration: string): HogFlowAction {
    return {
        id,
        type: 'delay',
        name: 'Delay',
        description: '',
        created_at: 0,
        updated_at: 0,
        config: { delay_duration: duration },
    } as HogFlowAction
}

function branchAction(id: string): HogFlowAction {
    return {
        id,
        type: 'conditional_branch',
        name: 'Branch',
        description: '',
        created_at: 0,
        updated_at: 0,
        config: { conditions: [] },
    } as HogFlowAction
}

const TRIGGER: HogFlowAction = {
    id: 'trigger_node',
    type: 'trigger',
    name: 'Trigger',
    description: '',
    created_at: 0,
    updated_at: 0,
    config: {
        type: 'event',
        filters: { events: [{ id: 'user signed up', name: 'user signed up', type: 'events', order: 0 }] },
    },
} as HogFlowAction

const EXIT: HogFlowAction = {
    id: 'exit_node',
    type: 'exit',
    name: 'Exit',
    description: '',
    created_at: 0,
    updated_at: 0,
    config: { reason: 'Done' },
} as HogFlowAction

// Three emails whose stored order differs from the flow order, with a branch on the way to the last one.
const SEQUENCE: Partial<HogFlowTemplateApi> = {
    id: 'onboarding-sequence',
    name: 'Onboarding sequence',
    scope: 'global',
    tags: [],
    starts_on: { kind: 'event', events: ['user signed up', 'signed_up'], detail: '' },
    actions: [
        TRIGGER,
        emailAction('email_last', 'Last reminder'),
        emailAction('email_first', 'Welcome!'),
        delayAction('delay_1', '1d'),
        emailAction('email_second', 'Still there?'),
        delayAction('delay_2', '2d'),
        branchAction('branch_1'),
        EXIT,
    ] as unknown as HogFlowTemplateApi['actions'],
    edges: [
        { from: 'trigger_node', to: 'email_first', type: 'continue' },
        { from: 'email_first', to: 'delay_1', type: 'continue' },
        { from: 'delay_1', to: 'email_second', type: 'continue' },
        { from: 'email_second', to: 'delay_2', type: 'continue' },
        { from: 'delay_2', to: 'branch_1', type: 'continue' },
        { from: 'branch_1', to: 'exit_node', type: 'continue' },
        { from: 'branch_1', to: 'email_last', type: 'branch' },
        { from: 'email_last', to: 'exit_node', type: 'continue' },
    ],
    exit_condition: 'exit_only_at_end',
    conversion: { filters: [] },
}

const SINGLE: Partial<HogFlowTemplateApi> = {
    id: 'single-email',
    name: 'One email',
    scope: 'global',
    tags: [],
    starts_on: { kind: 'event', events: ['$pageview'], detail: '' },
    actions: [TRIGGER, emailAction('email_only', 'Hello'), EXIT] as unknown as HogFlowTemplateApi['actions'],
    edges: [
        { from: 'trigger_node', to: 'email_only', type: 'continue' },
        { from: 'email_only', to: 'exit_node', type: 'continue' },
    ],
}

function editedEmail(subject: string): EmailTemplate {
    return {
        subject,
        html: `<p>${subject} edited</p>`,
        text: `${subject} edited`,
        design: { body: { rows: [], values: { subject: `${subject} edited` } } },
        from: { integrationId: 99 },
        to: '{{ person.properties.email }}',
    } as EmailTemplate
}

function emailStepsOf(workflow: Partial<HogFlow>): Record<string, any> {
    return Object.fromEntries(
        (workflow.actions ?? [])
            .filter((action) => action.type === 'function_email')
            .map((action) => [action.id, action.config.inputs.email.value])
    )
}

describe('firstRunMakeItYoursLogic', () => {
    let logic: ReturnType<typeof firstRunMakeItYoursLogic.build>
    let integrations: Partial<IntegrationConfigApi>[]
    let createdWorkflows: Partial<HogFlow>[]
    let createResponse: [number, Record<string, unknown>]
    let invocations: Record<string, any>[]
    let invocationResponse: Record<string, unknown>
    let completedSetupTasks: string[]
    let teamUpdates: Record<string, any>[]
    let requestOrder: string[]
    let persistedTeam: typeof MOCK_DEFAULT_TEAM

    beforeEach(() => {
        completedSetupTasks = []
        teamUpdates = []
        requestOrder = []
        persistedTeam = { ...MOCK_DEFAULT_TEAM }
        integrations = [SENDER]
        createdWorkflows = []
        createResponse = [201, { id: 'wf-1', status: 'active' }]
        invocations = []
        invocationResponse = { status: 'success', logs: [], nextActionId: null }
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flow_templates/': { count: 2, results: [SEQUENCE, SINGLE] },
                '/api/projects/:team_id/event_definitions/': ({ request }) => {
                    const names = new URL(request.url).searchParams.get('names')?.split(',') ?? []
                    const seen = names.filter((name) => ['signed_up', '$pageview'].includes(name))
                    return [
                        200,
                        {
                            count: seen.length,
                            results: seen.map((name) => ({ id: name, name, last_seen_at: '2026-10-01T00:00:00Z' })),
                        },
                    ]
                },
                '/api/projects/:team_id/integrations/': () => [200, { results: integrations }],
            },
            post: {
                '/api/projects/:team_id/hog_flows/': async ({ request }) => {
                    requestOrder.push('create workflow')
                    createdWorkflows.push((await request.json()) as Partial<HogFlow>)
                    return createResponse
                },
                '/api/projects/:team_id/hog_flows/new/invocations/': async ({ request }) => {
                    invocations.push((await request.json()) as Record<string, any>)
                    return [200, invocationResponse]
                },
            },
            patch: {
                '/api/projects/:team_id/': async ({ request }) => {
                    const update = (await request.json()) as Record<string, any>
                    if (update.workflows_config) {
                        requestOrder.push('update team')
                        teamUpdates.push(update)
                    }
                    if (update.onboarding_tasks) {
                        completedSetupTasks = Object.keys(update.onboarding_tasks).filter(
                            (taskId) => update.onboarding_tasks[taskId] === 'completed'
                        )
                    }
                    persistedTeam = { ...persistedTeam, ...update }
                    return [200, persistedTeam]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN]: true })
        globalSetupLogic.mount()
        window.POSTHOG_APP_CONTEXT!.resource_access_control = { hog_flow: 'editor' } as any
    })

    afterEach(() => {
        logic?.unmount()
        window.localStorage.clear()
    })

    async function open(templateId: string): Promise<void> {
        logic = firstRunMakeItYoursLogic({ templateId })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({ pickedTemplate: expect.anything() })
    }

    it('lists the emails in flow order with their timing and opens the first one', async () => {
        await open('onboarding-sequence')

        expect(logic.values.templateEmails.map(({ id, subject, timing }) => ({ id, subject, timing }))).toEqual([
            { id: 'email_first', subject: 'Welcome!', timing: 'Right away' },
            { id: 'email_second', subject: 'Still there?', timing: 'After 1 day' },
            { id: 'email_last', subject: 'Last reminder', timing: 'After 3 days' },
        ])
        expect(logic.values.openEmail?.id).toBe('email_first')
        expect(logic.values.openEmailPosition).toEqual({ index: 1, total: 3 })
    })

    it('keeps the edits of every email while switching between them', async () => {
        await open('onboarding-sequence')

        logic.actions.editEmail('email_first', editedEmail('Welcome!'))
        logic.actions.openEmail('email_second')
        logic.actions.editEmail('email_second', editedEmail('Still there?'))
        logic.actions.openEmail('email_first')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.openEmail).toMatchObject({
            id: 'email_first',
            edited: true,
            email: { subject: 'Welcome!', text: 'Welcome! edited' },
        })
        expect(logic.values.editedEmailIds).toEqual(['email_first', 'email_second'])
        expect(logic.values.openEmailPosition).toEqual({ index: 1, total: 3 })
    })

    it.each([
        { enabled: true, status: 'active', firstRunEnabled: true, completesLaunchTask: true },
        { enabled: false, status: 'draft', firstRunEnabled: true, completesLaunchTask: false },
        { enabled: false, status: 'draft', firstRunEnabled: false, completesLaunchTask: false },
    ])(
        'honors first-run=$firstRunEnabled when creating a $status workflow with edits, sender and matched event',
        async ({ enabled, status, firstRunEnabled, completesLaunchTask }) => {
            createResponse = [201, { id: 'wf-1', status }]
            const capture = jest.spyOn(posthog, 'capture').mockImplementation()
            await open('onboarding-sequence')
            logic.actions.editEmail('email_first', editedEmail('Welcome!'))
            logic.actions.openEmail('email_last')
            logic.actions.editEmail('email_last', editedEmail('Last reminder'))
            logic.actions.setEnableWorkflow(enabled)
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN]: firstRunEnabled })
            const pathnameBefore = router.values.location.pathname

            logic.actions.createWorkflow()
            await expectLogic(logic).toFinishAllListeners()

            if (!firstRunEnabled) {
                expect(createdWorkflows).toHaveLength(0)
                expect(router.values.location.pathname).toBe(pathnameBefore)
                expect(window.localStorage.getItem('workflows-first-run-workflow-id')).toBeNull()
                expect(capture).not.toHaveBeenCalledWith('workflows first run workflow created', expect.anything())
                return
            }

            expect(createdWorkflows).toHaveLength(1)
            const created = createdWorkflows[0]
            expect(created).not.toHaveProperty('id')
            expect(created).not.toHaveProperty('team_id')
            expect(created).toMatchObject({ name: 'Onboarding sequence', status })
            expect(emailStepsOf(created)).toEqual({
                email_first: expect.objectContaining({ text: 'Welcome! edited', from: { integrationId: SENDER.id } }),
                email_second: expect.objectContaining({ text: 'Still there?', from: { integrationId: SENDER.id } }),
                email_last: expect.objectContaining({
                    text: 'Last reminder edited',
                    from: { integrationId: SENDER.id },
                }),
            })
            const trigger = created.actions?.find((action) => action.type === 'trigger')
            expect(trigger?.config).toEqual({
                type: 'event',
                filters: { events: [{ id: 'signed_up', name: 'signed_up', type: 'events', order: 0 }] },
            })
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(urls.workflow('wf-1', 'workflow'))
            expect(window.localStorage.getItem('workflows-first-run-workflow-id')).toBe('wf-1')
            expect(capture).toHaveBeenCalledWith('workflows first run workflow created', {
                template_id: 'onboarding-sequence',
                enabled,
                engagement_events: true,
            })
            expect(completedSetupTasks.includes(SetupTaskId.LaunchWorkflow)).toBe(completesLaunchTask)
        }
    )

    it.each([true, false])('sends the edited email only while first run is enabled=%s', async (enabled) => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()
        await open('onboarding-sequence')
        logic.actions.openEmail('email_second')
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.editEmail('email_second', editedEmail('Still there?'))
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN]: enabled })

        logic.actions.sendTest()
        await expectLogic(logic).toFinishAllListeners()

        if (!enabled) {
            expect(invocations).toHaveLength(0)
            expect(logic.values.testSendOutcome).toBeNull()
            expect(capture).not.toHaveBeenCalledWith('workflows first run test sent', expect.anything())
            return
        }

        expect(invocations).toHaveLength(1)
        const [invocation] = invocations
        expect(invocation).toMatchObject({ mock_async_functions: false, current_action_id: 'send_test_email' })
        const emailSteps = emailStepsOf(invocation.configuration)
        expect(emailSteps).toEqual({
            send_test_email: expect.objectContaining({
                text: 'Still there? edited',
                from: { integrationId: SENDER.id },
                to: { email: 'john.doe@posthog.com', name: '' },
            }),
        })
        expect(logic.values.testSendOutcome).toEqual({ kind: 'sent', recipient: 'john.doe@posthog.com' })
        expect(capture).toHaveBeenCalledWith('workflows first run test sent', { skipped: false })
        expect(completedSetupTasks).toContain(SetupTaskId.SendWorkflowTestEmail)
    })

    it('shows why the worker skipped a test send', async () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()
        const reason = 'Skipping send: the recipient address has no mail server.'
        invocationResponse = {
            status: 'success',
            nextActionId: null,
            logs: [{ level: 'info', timestamp: '2026-10-05T00:00:00Z', message: reason }],
        }
        await open('onboarding-sequence')

        logic.actions.sendTest()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.testSendOutcome).toEqual({ kind: 'skipped', reason })
        expect(capture).toHaveBeenCalledWith('workflows first run test sent', { skipped: true })
        expect(completedSetupTasks).not.toContain(SetupTaskId.SendWorkflowTestEmail)
    })

    it('without a first-run sender disables test and enable with a reason, and still creates a draft', async () => {
        integrations = []
        await open('onboarding-sequence')

        expect(logic.values.sendTestDisabledReason).toBe('Connect an email sender first')
        expect(logic.values.enableDisabledReason).toBe('Connect an email sender first')
        expect(logic.values.enableWorkflow).toBe(false)

        logic.actions.createWorkflow()
        await expectLogic(logic).toFinishAllListeners()

        expect(createdWorkflows[0]).toMatchObject({ status: 'draft' })
        expect(emailStepsOf(createdWorkflows[0]).email_first.from).toEqual({ name: '', email: '' })
    })

    it('shows the server message of a rejected create and opens nothing', async () => {
        createResponse = [400, { type: 'validation_error', detail: 'Pick at least one event.', attr: 'actions' }]
        await open('onboarding-sequence')
        const pathnameBefore = router.values.location.pathname

        logic.actions.createWorkflow()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.createError).toBe('Pick at least one event.')
        expect(logic.values.createdWorkflowLoading).toBe(false)
        expect(router.values.location.pathname).toBe(pathnameBefore)
        expect(window.localStorage.getItem('workflows-first-run-workflow-id')).toBeNull()
        expect(teamUpdates).toEqual([])
    })

    describe('capture engagement events', () => {
        async function createAndSettle(): Promise<void> {
            logic.actions.createWorkflow()
            await expectLogic(logic).toFinishAllListeners()
            await expectLogic(teamLogic).toFinishAllListeners()
        }

        it('turns the setting on with one update of only that field, after the workflow is created', async () => {
            await open('onboarding-sequence')
            expect(logic.values.captureEngagementEvents).toBe(true)

            await createAndSettle()

            expect(requestOrder).toEqual(['create workflow', 'update team'])
            expect(teamUpdates).toEqual([{ workflows_config: { capture_workflows_engagement_events: true } }])
            expect(teamLogic.values.currentTeam?.workflows_config?.capture_workflows_engagement_events).toBe(true)
        })

        it('leaves the setting off when the switch is off', async () => {
            await open('onboarding-sequence')
            logic.actions.setCaptureEngagementEvents(false)

            await createAndSettle()

            expect(createdWorkflows).toHaveLength(1)
            expect(teamUpdates).toEqual([])
        })

        it('shows a member the switch off and disabled with a reason, and sends no update', async () => {
            teamLogic.actions.loadCurrentTeamSuccess({
                ...MOCK_DEFAULT_TEAM,
                effective_membership_level: OrganizationMembershipLevel.Member,
            })
            await open('onboarding-sequence')

            expect(logic.values.captureEngagementEvents).toBe(false)
            expect(logic.values.captureEngagementEventsDisabledReason).toBe(
                'Only project admins can turn on engagement events.'
            )

            await createAndSettle()

            expect(createdWorkflows).toHaveLength(1)
            expect(teamUpdates).toEqual([])
        })
    })

    describe('while the editor still holds a canvas edit it has not exported', () => {
        let templater: ReturnType<typeof emailTemplaterLogic.build>

        beforeEach(async () => {
            useMocks({ get: { '/api/projects/:team_id/messaging_templates/': { count: 0, results: [] } } })
            await open('onboarding-sequence')
            templater = emailTemplaterLogic({ type: 'native_email_template', value: null, onChange: () => {} })
            templater.mount()
            templater.cache.pendingDesignEdit = true
        })

        afterEach(() => {
            templater.unmount()
        })

        function editorExportsTheEdit(): void {
            templater.cache.pendingDesignEdit = false
            logic.actions.editEmail('email_first', editedEmail('Welcome!'))
        }

        it('switches emails only after the edit arrived, and keeps it', async () => {
            logic.actions.openEmail('email_second')
            await expectLogic(logic).toDispatchActions(['openEmail'])

            expect(logic.values.openEmail?.id).toBe('email_first')

            editorExportsTheEdit()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.openEmail?.id).toBe('email_second')
            expect(logic.values.edits.email_first.text).toBe('Welcome! edited')
        })

        it.each(
            (
                [
                    {
                        action: 'sendTest',
                        requests: () => invocations,
                        text: (body: any) => emailStepsOf(body.configuration).send_test_email.text,
                    },
                    {
                        action: 'createWorkflow',
                        requests: () => createdWorkflows,
                        text: (body: any) => emailStepsOf(body).email_first.text,
                    },
                ] as const
            ).flatMap((testCase) => [
                { ...testCase, enabled: true },
                { ...testCase, enabled: false },
            ])
        )('$action waits for the edit and honors first-run=$enabled', async ({ action, requests, text, enabled }) => {
            logic.actions[action]()
            await expectLogic(logic).toDispatchActions([action])

            expect(requests()).toHaveLength(0)

            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN]: enabled })
            editorExportsTheEdit()
            await expectLogic(logic).toFinishAllListeners()

            expect(requests()).toHaveLength(enabled ? 1 : 0)
            if (enabled) {
                expect(text(requests()[0])).toBe('Welcome! edited')
            }
        })
    })

    it('disables test and create for a user without editor access to workflows', async () => {
        window.POSTHOG_APP_CONTEXT!.resource_access_control = { hog_flow: 'viewer' } as any
        await open('onboarding-sequence')

        expect(logic.values.sendTestDisabledReason).toContain("You don't have sufficient permissions")
        expect(logic.values.createDisabledReason).toContain("You don't have sufficient permissions")
    })
})
