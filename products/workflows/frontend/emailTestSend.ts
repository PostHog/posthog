import { HogflowTestResult } from './Workflows/hogflows/steps/types'
import { HogFlow, HogFlowAction, HogFlowEdge } from './Workflows/hogflows/types'
import { EXIT_NODE_ID, NEW_WORKFLOW, TRIGGER_NODE_ID } from './Workflows/workflowLogic'

// Fixed id for the single email action in the synthetic test flow. The edges below reference it,
// and it goes over as `current_action_id` so the worker runs just this node.
export const TEST_EMAIL_ACTION_ID = 'send_test_email'

// Every reason the email worker declines a send is logged behind this prefix
// (nodejs/src/cdp/services/messaging/email-validation.service.ts).
const SKIP_LOG_PREFIX = 'Skipping send:'

/**
 * The reason the worker declined to send, if it did.
 *
 * A declined send still finishes the step cleanly, so the invocation comes back `success` and the
 * reason appears only in the logs. Reading the status alone reports a test as delivered when
 * nothing was sent, and the sender waits for mail that never arrives.
 */
export function findTestSendSkipReason(result: HogflowTestResult | null): string | undefined {
    return result?.logs?.find((log) => log.message?.includes(SKIP_LOG_PREFIX))?.message
}

/**
 * A throwaway one-step flow that exists only for a test invocation, so a test send never runs the
 * surrounding workflow or reaches the audience the real send would.
 *
 * Callers pass whatever email content they are testing. The recipient is applied here rather than
 * by each caller, because one visible recipient and no cc/bcc is what makes the send safe.
 */
export function buildSingleEmailTestFlow({
    email,
    recipientEmail,
    name,
    teamId,
    templating = 'liquid',
}: {
    email: Record<string, any>
    recipientEmail: string
    name: string
    teamId?: number | null
    templating?: 'hog' | 'liquid'
}): HogFlow {
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
                        // A test send has exactly one visible recipient - never carry over a cc/bcc
                        // that happened to be on the content being tested.
                        cc: '',
                        bcc: '',
                        to: { email: recipientEmail, name: '' },
                    },
                    templating,
                },
            },
        },
    }

    const edges: HogFlowEdge[] = [
        { from: TRIGGER_NODE_ID, to: TEST_EMAIL_ACTION_ID, type: 'continue' },
        { from: TEST_EMAIL_ACTION_ID, to: EXIT_NODE_ID, type: 'continue' },
    ]

    return {
        ...NEW_WORKFLOW,
        team_id: teamId ?? NEW_WORKFLOW.team_id,
        name,
        actions: [NEW_WORKFLOW.actions[0], emailAction, NEW_WORKFLOW.actions[1]],
        edges,
    }
}
