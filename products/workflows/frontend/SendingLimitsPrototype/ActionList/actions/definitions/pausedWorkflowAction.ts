import type { WorkflowEmailSendingRatesApi } from 'products/workflows/frontend/generated/api.schemas'

import { workflowName } from '../../reputationUtils'
import { defineReputationAction } from '../defineReputationAction'
import { LOWER_RATES_DOCS, openWorkflow } from '../reputationActionCtas'

/**
 * A workflow whose email is paused. The workflow page opens with the pause banner. It has a resume
 * button, a disabled reason for a viewer, or a contact support button when only support can
 * resume the workflow.
 */
export const pausedWorkflowAction = defineReputationAction<WorkflowEmailSendingRatesApi>({
    kind: 'paused-workflow',
    detect: ({ response }) => response.workflows.filter((workflow) => workflow.email_sending_paused),
    content: (workflow) => ({
        key: `paused:${workflow.hog_flow_id}`,
        rank: { severity: 'high', slot: 'pausedWorkflow' },
        blocksSending: true,
        title: `${workflowName(workflow)} is paused`,
        description: `${workflow.email_sending_paused_reason || 'Its email is paused.'} Check where its audience comes from, then resume sending from the workflow page. If only support can resume it, contact support from there.`,
        docsLink: LOWER_RATES_DOCS,
    }),
    cta: openWorkflow,
})
