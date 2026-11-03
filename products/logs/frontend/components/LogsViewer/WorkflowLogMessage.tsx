import { useValues } from 'kea'

import { renderWorkflowLogMessage } from 'products/workflows/frontend/Workflows/logs/log-utils'
import { workflowNameLogic } from 'products/workflows/frontend/Workflows/workflowNameLogic'

export function WorkflowLogMessage({ workflowId, message }: { workflowId: string; message: string }): JSX.Element {
    const { workflow } = useValues(workflowNameLogic({ id: workflowId }))

    // Plain text while the workflow loads, or when it is deleted or hidden from this user.
    return workflow ? renderWorkflowLogMessage(workflow, message) : <>{message}</>
}
