/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import { sandboxSenderLogic } from '../../../../Channels/sandboxSenderLogic'
import { workflowLogic } from '../../../workflowLogic'
import type { HogFlow, HogFlowAction } from '../../types'
import { emailSenderControlLogic } from './emailSenderControlLogic'

const STATUS = {
    integration_id: 11,
    from_address: 'sandbox@example.com',
    display_name: 'Example via PostHog',
    organization_blocked: false,
    adoption_enabled: true,
}
const VERIFYING_SENDER = { id: 9, kind: 'email', config: { verified: false } } as unknown as IntegrationType

function ownStep(value: Record<string, any> = {}): HogFlowAction {
    return {
        id: 'email_step',
        type: 'function_email',
        name: 'Welcome',
        description: '',
        created_at: 0,
        updated_at: 0,
        config: {
            template_id: 'template-email',
            inputs: {
                email: {
                    templating: 'liquid',
                    value: { to: { email: '{{ person.properties.email }}' }, subject: 'Hi', from: {}, ...value },
                },
            },
        },
    } as HogFlowAction
}

const SANDBOX_STEP = {
    id: 'email_step',
    type: 'email_sandbox',
    name: 'Welcome',
    description: '',
    created_at: 0,
    updated_at: 0,
    config: {
        inputs: {
            email: { templating: 'liquid', value: { to: { email: '{{ person.properties.email }}' }, subject: 'Hi' } },
        },
    },
} as HogFlowAction

describe('emailSenderControlLogic', () => {
    let wfLogic: ReturnType<typeof workflowLogic.build>
    let logic: ReturnType<typeof emailSenderControlLogic.build>

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
    })

    async function setUp(
        step: HogFlowAction,
        status: Record<string, any> = STATUS,
        workflowInfo: Partial<HogFlow> = {},
        senders: IntegrationType[] = [VERIFYING_SENDER]
    ): Promise<void> {
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': { results: senders, next: null },
                '/api/projects/:team_id/workflow_email_sandbox/status/': status,
            },
        })
        initKeaTests()
        wfLogic = workflowLogic({ id: 'new' })
        wfLogic.mount()
        await expectLogic(wfLogic).toFinishAllListeners()
        wfLogic.actions.setWorkflowInfo({ ...workflowInfo, actions: [...wfLogic.values.workflow.actions, step] })
        integrationsLogic.mount()
        sandboxSenderLogic.mount()
        await expectLogic(integrationsLogic).toFinishAllListeners()
        logic = emailSenderControlLogic({ workflowLogicProps: wfLogic.props, actionId: step.id })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    function storedStep(): HogFlowAction | undefined {
        return wfLogic.values.workflow.actions.find((action) => action.id === 'email_step')
    }

    it('switches an own step without own-only settings to the sandbox sender without asking', async () => {
        await setUp(ownStep({ from: { integrationId: 7 } }))

        logic.actions.chooseSender('sandbox')

        expect(storedStep()).toMatchObject({ id: 'email_step', type: 'email_sandbox', name: 'Welcome' })
        expect(logic.values.pendingSwitch).toBeNull()
    })

    it.each([
        ['cancel', 'function_email'],
        ['confirm', 'email_sandbox'],
    ])('asks before dropping own-only settings, and %s decides the step kind', async (decision, expectedType) => {
        await setUp(
            ownStep({ from: { integrationId: 7, name: 'Support' }, replyTo: 'help@example.com', cc: 'a@example.com' })
        )

        logic.actions.chooseSender('sandbox')
        expect(logic.values.pendingSwitch).toEqual({ droppedSettings: ['sender_override', 'reply_to', 'cc_bcc'] })
        expect(storedStep()?.type).toEqual('function_email')

        const decide = decision === 'cancel' ? logic.actions.cancelSwitch : logic.actions.confirmSwitch
        decide()

        expect(logic.values.pendingSwitch).toBeNull()
        expect(storedStep()?.type).toEqual(expectedType)
    })

    it.each<[string, HogFlowAction, Record<string, any>, boolean, Partial<HogFlow>]>([
        ['an own step when adoption is on and no sender is verified', ownStep(), STATUS, true, {}],
        ['an own step when adoption is off', ownStep(), { ...STATUS, adoption_enabled: false }, false, {}],
        [
            'an own step when the organization is blocked',
            ownStep(),
            { ...STATUS, organization_blocked: true },
            false,
            {},
        ],
        ['a sandbox step when adoption is off', SANDBOX_STEP, { ...STATUS, adoption_enabled: false }, true, {}],
        ['an own step in a workflow another product owns', ownStep(), STATUS, false, { origin_product: 'broadcasts' }],
        ['an own step whose id the sandbox sender rejects', { ...ownStep(), id: 'welcome.email' }, STATUS, false, {}],
    ])('offers the sandbox sender for %s', async (_, step, status, expected, workflowInfo) => {
        const capture = jest.spyOn(posthog, 'capture')

        await setUp(step, status, workflowInfo)

        expect(logic.values.showSandboxOption).toEqual(expected)
        expect(capture.mock.calls.filter(([event]) => event === 'workflows sandbox sender offered')).toEqual(
            expected ? [['workflows sandbox sender offered', { step_type: step.type }]] : []
        )
    })

    it('does not offer the sandbox sender for a sensitive own step, which the sandbox sender would make not sensitive', async () => {
        await setUp({ ...ownStep(), config: { ...ownStep().config, sensitive: true } } as HogFlowAction, STATUS, {})

        expect(logic.values.showSandboxOption).toBe(false)
    })
})
