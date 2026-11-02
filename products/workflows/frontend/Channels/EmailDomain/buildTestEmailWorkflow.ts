import { createExampleEvent } from '../../Workflows/hogflows/testEventFactory'
import type { HogFlow, HogFlowAction, HogFlowEdge } from '../../Workflows/hogflows/types'
import { EXIT_NODE_ID, NEW_WORKFLOW, TRIGGER_NODE_ID } from '../../Workflows/workflowLogic'

const TEST_EMAIL_ACTION_ID = 'send_test_email'

export interface TestEmailWorkflowInput {
    integrationId: number
    teamId: number | null
    domain: string
    recipient: string
}

export interface TestEmailInvocation {
    configuration: HogFlow
    globals: ReturnType<typeof createExampleEvent>
    mock_async_functions: false
    current_action_id: string
}

const testEmailAction = (integrationId: number, domain: string, recipient: string): HogFlowAction => {
    const text = `Your sending domain ${domain} is set up. Emails from PostHog Workflows will arrive like this one.`
    return {
        id: TEST_EMAIL_ACTION_ID,
        type: 'function_email',
        name: 'Send test email',
        description: '',
        created_at: 0,
        updated_at: 0,
        config: {
            template_id: 'template-email',
            inputs: {
                email: {
                    value: {
                        design: null,
                        subject: `Test email from ${domain}`,
                        html: `<p>${text}</p>`,
                        text,
                        from: { integrationId },
                        to: { email: recipient, name: '' },
                        cc: '',
                        bcc: '',
                    },
                    templating: 'liquid',
                },
            },
        },
    }
}

export const buildTestEmailInvocation = ({
    integrationId,
    teamId,
    domain,
    recipient,
}: TestEmailWorkflowInput): TestEmailInvocation => {
    const edges: HogFlowEdge[] = [
        { from: TRIGGER_NODE_ID, to: TEST_EMAIL_ACTION_ID, type: 'continue' },
        { from: TEST_EMAIL_ACTION_ID, to: EXIT_NODE_ID, type: 'continue' },
    ]
    const configuration: HogFlow = {
        ...NEW_WORKFLOW,
        team_id: teamId ?? NEW_WORKFLOW.team_id,
        name: 'Test email',
        actions: [NEW_WORKFLOW.actions[0], testEmailAction(integrationId, domain, recipient), NEW_WORKFLOW.actions[1]],
        edges,
    }
    return {
        configuration,
        globals: createExampleEvent(teamId ?? undefined, configuration.name, '$pageview', recipient),
        mock_async_functions: false,
        current_action_id: TEST_EMAIL_ACTION_ID,
    }
}
