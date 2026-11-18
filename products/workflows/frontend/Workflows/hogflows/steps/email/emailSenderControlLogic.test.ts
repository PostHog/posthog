import { integrationsLogic } from 'lib/integrations/integrationsLogic'

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
const OWN_SENDER = { id: 7, kind: 'email', config: { verified: true } } as unknown as IntegrationType

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

    function setUp(step: HogFlowAction, status: Record<string, any> = STATUS): void {
        initKeaTests()
        wfLogic = workflowLogic({ id: 'new' })
        wfLogic.mount()
        wfLogic.actions.setWorkflowInfo({ actions: [...wfLogic.values.workflow.actions, step] })
        integrationsLogic.mount()
        integrationsLogic.actions.loadIntegrationsSuccess([OWN_SENDER])
        sandboxSenderLogic.mount()
        sandboxSenderLogic.actions.loadSandboxStatusSuccess(status as any)
        logic = emailSenderControlLogic({ workflowLogicProps: wfLogic.props, actionId: step.id })
        logic.mount()
    }

    function storedStep(): HogFlowAction | undefined {
        return wfLogic.values.workflow.actions.find((action) => action.id === 'email_step')
    }

    it('switches an own step without own-only settings to the sandbox sender without asking', () => {
        setUp(ownStep({ from: { integrationId: 7 } }))

        logic.actions.chooseSender('sandbox')

        expect(storedStep()).toMatchObject({ id: 'email_step', type: 'email_sandbox', name: 'Welcome' })
        expect(logic.values.pendingSwitch).toBeNull()
    })

    it.each([
        ['cancel', 'function_email'],
        ['confirm', 'email_sandbox'],
    ])('asks before dropping own-only settings, and %s decides the step kind', async (decision, expectedType) => {
        setUp(
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

    it('switches a sandbox step to the chosen own sender', () => {
        setUp(SANDBOX_STEP)

        logic.actions.chooseSender(7)

        expect(storedStep()).toMatchObject({
            type: 'function_email',
            config: { template_id: 'template-email', inputs: { email: { value: { from: { integrationId: 7 } } } } },
        })
    })

    it.each<[string, HogFlowAction, Record<string, any>, boolean, Partial<HogFlow>]>([
        ['an own step when adoption is on', ownStep(), STATUS, true, {}],
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
    ])('offers the sandbox sender for %s', (_, step, status, expected, workflowInfo) => {
        setUp(step, status)
        wfLogic.actions.setWorkflowInfo(workflowInfo)

        expect(logic.values.showSandboxOption).toEqual(expected)
    })
})
