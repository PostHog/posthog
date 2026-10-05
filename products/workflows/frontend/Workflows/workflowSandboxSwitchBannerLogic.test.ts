import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HogFlow, HogFlowAction } from './hogflows/types'
import { workflowLogic } from './workflowLogic'
import { workflowSandboxSwitchBannerLogic } from './workflowSandboxSwitchBannerLogic'

const WORKFLOW_ID = 'wf-sandbox-switch-1'
const SANDBOX_SENDER_ID = 7
const OWN_SENDER_ID = 8
const SECOND_OWN_SENDER_ID = 9

const SANDBOX_SENDER = {
    id: SANDBOX_SENDER_ID,
    kind: 'email',
    display_name: 'Acme via PostHog <sandbox@example.com>',
    config: { provider: 'sandbox', name: 'Acme via PostHog', email: 'sandbox@example.com', verified: true },
}
const OWN_SENDER = {
    id: OWN_SENDER_ID,
    kind: 'email',
    display_name: 'Acme <hello@acme.example.com>',
    config: { provider: 'ses', domain: 'acme.example.com', email: 'hello@acme.example.com', verified: true },
}
const SECOND_OWN_SENDER = {
    id: SECOND_OWN_SENDER_ID,
    kind: 'email',
    display_name: 'Acme support <support@acme.example.com>',
    config: { provider: 'ses', domain: 'acme.example.com', email: 'support@acme.example.com', verified: true },
}
const UNVERIFIED_OWN_SENDER = { ...OWN_SENDER, id: 10, config: { ...OWN_SENDER.config, verified: false } }

const emailStep = (id: string, from: Record<string, unknown>): HogFlowAction => ({
    id,
    type: 'function_email',
    name: 'Send email',
    description: '',
    created_at: 0,
    updated_at: 0,
    config: {
        template_id: 'template-email',
        inputs: {
            email: {
                value: {
                    to: { email: 'recipient@example.com' },
                    from,
                    subject: 'Hello',
                    html: '<p>Hi</p>',
                    text: 'Hi',
                },
                templating: 'liquid',
            },
        },
    },
})

const makeWorkflow = (steps: HogFlowAction[]): HogFlow => ({
    id: WORKFLOW_ID,
    name: 'Sandbox switch test',
    actions: [
        {
            id: 'trigger_node',
            type: 'trigger',
            name: 'Trigger',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { type: 'event', filters: {} },
        },
        ...steps,
        {
            id: 'exit_node',
            type: 'exit',
            name: 'Exit',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { reason: 'Default exit' },
        },
    ],
    edges: [],
    conversion: { filters: [] },
    exit_condition: 'exit_only_at_end',
    version: 1,
    status: 'draft',
    team_id: 1,
    trigger: { type: 'event', filters: {} } as HogFlow['trigger'],
    created_at: '2026-05-01T00:00:00.000Z',
    updated_at: '2026-05-01T00:00:00.000Z',
})

const senderOf = (workflow: HogFlow, stepId: string): unknown =>
    workflow.actions.find((action) => action.id === stepId)?.config.inputs?.email?.value?.from

describe('workflowSandboxSwitchBannerLogic', () => {
    let logic: ReturnType<typeof workflowSandboxSwitchBannerLogic.build>
    let capture: jest.SpyInstance
    let savedWorkflow: HogFlow
    let integrationsPayload: unknown[]

    const mountWith = async ({
        steps,
        integrations,
        flag = true,
    }: {
        steps: HogFlowAction[]
        integrations: unknown[]
        flag?: boolean
    }): Promise<void> => {
        savedWorkflow = makeWorkflow(steps)
        integrationsPayload = integrations
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(
            flag ? [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER] : [],
            flag ? { [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER]: true } : {}
        )
        logic = workflowSandboxSwitchBannerLogic({ id: WORKFLOW_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions([
            workflowLogic({ id: WORKFLOW_ID }).actionCreators.loadWorkflowSuccess,
            'loadIntegrationsSuccess',
        ])
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': () => [200, savedWorkflow],
                '/api/projects/:team_id/integrations/': () => [200, { results: integrationsPayload }],
                '/api/projects/:team_id/hog_function_templates/': () => new Promise(() => {}),
            },
            patch: {
                '/api/environments/:team_id/hog_flows/:id/': async ({ request }) => [
                    200,
                    { ...savedWorkflow, ...((await request.json()) as Partial<HogFlow>) },
                ],
            },
        })
        capture = jest.spyOn(posthog, 'capture').mockImplementation()
    })

    afterEach(() => {
        logic?.unmount()
        featureFlagLogic.actions.setFeatureFlags([], {})
        capture.mockRestore()
    })

    it.each([
        {
            case: 'a sandbox email step and a verified own sender',
            steps: [emailStep('email_1', { integrationId: SANDBOX_SENDER_ID })],
            integrations: [SANDBOX_SENDER, OWN_SENDER],
            flag: true,
            visible: true,
        },
        {
            case: 'no verified own sender',
            steps: [emailStep('email_1', { integrationId: SANDBOX_SENDER_ID })],
            integrations: [SANDBOX_SENDER, UNVERIFIED_OWN_SENDER],
            flag: true,
            visible: false,
        },
        {
            case: 'no email step on the sandbox sender',
            steps: [emailStep('email_1', { integrationId: OWN_SENDER_ID })],
            integrations: [SANDBOX_SENDER, OWN_SENDER],
            flag: true,
            visible: false,
        },
        {
            case: 'the sandbox sender flag off',
            steps: [emailStep('email_1', { integrationId: SANDBOX_SENDER_ID })],
            integrations: [SANDBOX_SENDER, OWN_SENDER],
            flag: false,
            visible: false,
        },
    ])('shows the banner only with $case', async ({ steps, integrations, flag, visible }) => {
        await mountWith({ steps, integrations, flag })

        expect(logic.values.bannerVisible).toBe(visible)
        expect(capture.mock.calls.filter(([event]) => event === 'workflows sandbox switch banner shown')).toHaveLength(
            visible ? 1 : 0
        )
    })

    it('reports the banner once per workflow view even when integrations reload', async () => {
        await mountWith({
            steps: [emailStep('email_1', { integrationId: SANDBOX_SENDER_ID })],
            integrations: [SANDBOX_SENDER, OWN_SENDER],
        })

        await expectLogic(logic, () => {
            integrationsLogic.actions.loadIntegrations()
        }).toDispatchActions(['loadIntegrationsSuccess'])

        expect(capture.mock.calls.filter(([event]) => event === 'workflows sandbox switch banner shown')).toHaveLength(
            1
        )
    })

    it('switches every sandbox email step to the own sender as an unsaved change', async () => {
        await mountWith({
            steps: [
                emailStep('email_1', { integrationId: SANDBOX_SENDER_ID }),
                emailStep('email_2', { integrationId: OWN_SENDER_ID, name: 'Acme', email: 'hello@acme.example.com' }),
                emailStep('email_3', { integrationId: SANDBOX_SENDER_ID }),
            ],
            integrations: [SANDBOX_SENDER, OWN_SENDER],
        })
        const workflow = workflowLogic({ id: WORKFLOW_ID })

        await expectLogic(logic, () => {
            logic.actions.switchToOwnSender(OWN_SENDER_ID)
        }).toDispatchActions(['setWorkflowValues'])

        expect(senderOf(workflow.values.workflow, 'email_1')).toEqual({ integrationId: OWN_SENDER_ID })
        expect(senderOf(workflow.values.workflow, 'email_2')).toEqual({
            integrationId: OWN_SENDER_ID,
            name: 'Acme',
            email: 'hello@acme.example.com',
        })
        expect(senderOf(workflow.values.workflow, 'email_3')).toEqual({ integrationId: OWN_SENDER_ID })
        expect(senderOf(workflow.values.originalWorkflow!, 'email_1')).toEqual({ integrationId: SANDBOX_SENDER_ID })
        expect(workflow.values.hasUnsavedChanges).toBe(true)
        expect(logic.values.bannerVisible).toBe(false)
        expect(capture).toHaveBeenCalledWith('workflows sandbox sender switched', { email_step_count: 2 })
        expect(capture.mock.calls.filter(([event]) => event === 'workflows sandbox sender switched')).toHaveLength(1)
    })

    it('lets the user pick the own sender when several are verified', async () => {
        await mountWith({
            steps: [emailStep('email_1', { integrationId: SANDBOX_SENDER_ID })],
            integrations: [SANDBOX_SENDER, OWN_SENDER, SECOND_OWN_SENDER, UNVERIFIED_OWN_SENDER],
        })

        expect(logic.values.verifiedOwnSenders.map((sender) => sender.id)).toEqual([
            OWN_SENDER_ID,
            SECOND_OWN_SENDER_ID,
        ])

        await expectLogic(logic, () => {
            logic.actions.switchToOwnSender(SECOND_OWN_SENDER_ID)
        }).toDispatchActions(['setWorkflowValues'])

        expect(senderOf(workflowLogic({ id: WORKFLOW_ID }).values.workflow, 'email_1')).toEqual({
            integrationId: SECOND_OWN_SENDER_ID,
        })
    })
})
