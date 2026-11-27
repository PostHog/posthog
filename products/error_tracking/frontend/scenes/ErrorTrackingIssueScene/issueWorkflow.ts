import { router } from 'kea-router'

import { captureMessageAudienceClicked } from 'products/workflows/frontend/MessageAudience/messageAudience'
import { draftMessage } from 'products/workflows/frontend/MessageAudience/messageDrafts'
import {
    type WorkflowTriggerConfig,
    urlForNewWorkflowWithTrigger,
} from 'products/workflows/frontend/Workflows/workflowTriggerPrefill'

// pinned: reported as the click event's source, so renaming it splits the entry point's history
export const ISSUE_WORKFLOW_SOURCE = 'error_tracking'

function issueWorkflowTrigger(issueId: string): WorkflowTriggerConfig {
    return {
        type: 'event',
        filters: {
            events: [{ id: '$exception', name: '$exception', type: 'events' }],
            properties: [{ key: '$exception_issue_id', value: issueId, operator: 'exact', type: 'event' }],
        },
    }
}

/** Opens a new workflow that emails people each time they hit this issue. */
export function openIssueWorkflow(issueId: string): void {
    captureMessageAudienceClicked(ISSUE_WORKFLOW_SOURCE, 'workflow')
    router.actions.push(
        urlForNewWorkflowWithTrigger(
            issueWorkflowTrigger(issueId),
            ISSUE_WORKFLOW_SOURCE,
            draftMessage({ kind: 'issue_hit' }),
            {
                source: 'error_tracking',
                source_id: issueId,
            }
        )
    )
}
