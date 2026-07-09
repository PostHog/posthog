import { useValues } from 'kea'

import { HogInvocations } from 'scenes/hog-functions/invocations/HogInvocations'

import { renderWorkflowLogMessage } from './logs/log-utils'
import { workflowLogic } from './workflowLogic'

/**
 * Workflow-side wrapper around the shared `HogInvocations` component,
 * scoped to `function_kind = 'hog_flow'`. The component does all the work —
 * this file exists so the workflow scene can wire its own tab without
 * leaking the cross-product import into every call site.
 *
 * Passes the workflow-aware log renderer so event/person/action tokens in the
 * per-run logs become links, matching the standalone Logs tab.
 */
export function WorkflowInvocations({ id }: { id: string }): JSX.Element | null {
    const { workflow } = useValues(workflowLogic)
    return (
        <HogInvocations
            id={id}
            functionKind="hog_flow"
            renderLogMessage={workflow ? (m) => renderWorkflowLogMessage(workflow, m) : undefined}
        />
    )
}
