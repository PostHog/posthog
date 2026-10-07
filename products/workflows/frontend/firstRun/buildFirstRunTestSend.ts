import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import type { CyclotronJobInvocationGlobals } from '~/types'

import { createExampleEvent } from '../Workflows/hogflows/testEventFactory'
import type { HogFlow, HogFlowAction, HogFlowEdge } from '../Workflows/hogflows/types'
import { EXIT_NODE_ID, NEW_WORKFLOW, TRIGGER_NODE_ID } from '../Workflows/workflowLogic'
import type { FirstRunSender } from './firstRunSenderLogic'

// Fixed id for the single email action in the synthetic test flow. The edges reference it, and it
// goes over as `current_action_id` so the worker runs just this node.
const TEST_EMAIL_ACTION_ID = 'send_test_email'

export interface FirstRunTestSendInput {
    email: EmailTemplate
    sender: Pick<FirstRunSender, 'id'>
    recipientEmail: string
    workflowName: string
    teamId: number | null
}

export interface FirstRunTestSend {
    configuration: HogFlow
    globals: CyclotronJobInvocationGlobals
    mock_async_functions: boolean
    current_action_id: string
}

export function buildFirstRunTestSend({
    email,
    sender,
    recipientEmail,
    workflowName,
    teamId,
}: FirstRunTestSendInput): FirstRunTestSend {
    const emailAction: HogFlowAction = {
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
                        ...email,
                        // One visible recipient on a test, whatever the template carries.
                        cc: '',
                        bcc: '',
                        from: { integrationId: sender.id },
                        to: { email: recipientEmail, name: '' },
                    },
                    templating: 'liquid',
                },
            },
        },
    }
    const edges: HogFlowEdge[] = [
        { from: TRIGGER_NODE_ID, to: TEST_EMAIL_ACTION_ID, type: 'continue' },
        { from: TEST_EMAIL_ACTION_ID, to: EXIT_NODE_ID, type: 'continue' },
    ]
    const configuration: HogFlow = {
        ...NEW_WORKFLOW,
        team_id: teamId ?? NEW_WORKFLOW.team_id,
        name: workflowName,
        actions: [NEW_WORKFLOW.actions[0], emailAction, NEW_WORKFLOW.actions[1]],
        edges,
    }
    return {
        configuration,
        globals: createExampleEvent(teamId ?? undefined, workflowName, '$pageview', recipientEmail),
        // A test send is a real send. Mocking it would defeat the point.
        mock_async_functions: false,
        current_action_id: TEST_EMAIL_ACTION_ID,
    }
}
