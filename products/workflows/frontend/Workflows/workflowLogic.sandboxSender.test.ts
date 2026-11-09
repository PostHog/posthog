import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HogFlow, HogFlowAction } from './hogflows/types'
import { EXIT_NODE_ID, NEW_WORKFLOW, TRIGGER_NODE_ID, workflowLogic } from './workflowLogic'

const EMAIL_ID = 'action_function_email_welcome'

const template: HogFlow = {
    ...NEW_WORKFLOW,
    id: 'template-welcome',
    name: 'Welcome email',
    actions: [
        ...NEW_WORKFLOW.actions,
        {
            id: EMAIL_ID,
            type: 'function_email',
            name: 'Email',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: {
                template_id: 'template-email',
                inputs: {
                    email: {
                        templating: 'liquid',
                        value: {
                            to: { email: '{{ person.properties.email }}', name: '' },
                            from: {},
                            subject: 'Welcome',
                            text: 'Hello',
                            html: '<p>Hello</p>',
                        },
                    },
                },
            },
        } as HogFlowAction,
    ],
    edges: [
        { from: TRIGGER_NODE_ID, to: EMAIL_ID, type: 'continue' },
        { from: EMAIL_ID, to: EXIT_NODE_ID, type: 'continue' },
    ],
}

const verifiedSender = { id: 7, kind: 'email', config: { verified: true, email: 'hi@example.com' } }

const sandboxStatus = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({
    integration_id: 11,
    from_address: 'sandbox@example.com',
    display_name: 'Acme via PostHog',
    organization_blocked: false,
    adoption_enabled: true,
    ...overrides,
})

describe('workflowLogic first-run email sender', () => {
    let provisionCalls = 0

    function useSenderMocks(integrations: unknown[], status: Record<string, unknown>, provisionStatus = 200): void {
        provisionCalls = 0
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flow_templates/:id/': template,
                '/api/environments/:team_id/integrations/': { results: integrations },
                '/api/projects/:team_id/workflow_email_sandbox/status/': status,
            },
            post: {
                '/api/projects/:team_id/workflow_email_sandbox/provision/': () => {
                    provisionCalls += 1
                    return provisionStatus === 200
                        ? [200, { integration_id: 11 }]
                        : [provisionStatus, { detail: "This organization can't use the sandbox sender." }]
                },
            },
        })
    }

    async function openTemplate(): Promise<HogFlowAction | undefined> {
        initKeaTests()
        const logic = workflowLogic({ id: 'new', templateId: template.id })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])
        const email = logic.values.workflow.actions.find((action) => action.id === EMAIL_ID)
        logic.unmount()
        return email
    }

    it('prefers a verified own sender over the sandbox sender', async () => {
        useSenderMocks([verifiedSender], sandboxStatus())

        const email = await openTemplate()

        expect(email?.type).toEqual('function_email')
        expect((email?.config as any).inputs.email.value.from).toEqual({ integrationId: 7 })
    })

    it.each([
        ['the sender is already set up', sandboxStatus(), 0],
        ['the sender is set up on demand', sandboxStatus({ integration_id: null }), 1],
    ])('uses the sandbox sender when the project has no own sender and %s', async (_, status, expectedProvisions) => {
        useSenderMocks([], status)

        const email = await openTemplate()

        expect(email?.type).toEqual('email_sandbox')
        expect((email?.config as any).inputs.email.value).toEqual({
            to: { email: '{{ person.properties.email }}' },
            subject: 'Welcome',
            text: 'Hello',
            html: '<p>Hello</p>',
        })
        expect(provisionCalls).toEqual(expectedProvisions)
    })

    it.each([
        ['adoption is off', sandboxStatus({ adoption_enabled: false }), 200],
        ['the organization is blocked', sandboxStatus({ organization_blocked: true }), 200],
        ['setting up the sender fails', sandboxStatus({ integration_id: null }), 403],
    ])('keeps an own email step without a sender when %s', async (_, status, provisionStatus) => {
        useSenderMocks([], status, provisionStatus)

        const email = await openTemplate()

        expect(email?.type).toEqual('function_email')
        expect((email?.config as any).inputs.email.value.from).toEqual({})
    })
})
