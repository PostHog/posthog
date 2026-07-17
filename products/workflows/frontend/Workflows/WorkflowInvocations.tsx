import { useValues } from 'kea'

import { HogInvocations } from 'scenes/hog-functions/invocations/HogInvocations'

import { renderWorkflowLogMessage } from './logs/log-utils'
import { WorkflowBatchInvocations } from './WorkflowBatchInvocations'
import { workflowLogic } from './workflowLogic'

/**
 * Workflow-side wrapper around the shared `HogInvocations` component,
 * scoped to `function_kind = 'hog_flow'`. The component does all the work —
 * this file exists so the workflow scene can wire its own tab without
 * leaking the cross-product import into every call site.
 *
 * Batch-triggered workflows get the grouped-by-job view instead: their runs fan out
 * one child invocation per person, so we group them by batch job (and preview the
 * schedule's upcoming occurrences), matching the batch grouping the old Logs tab had.
 *
 * The flat view passes the workflow-aware log renderer so event/person/action tokens in
 * the per-run logs become links, matching the standalone Logs tab.
 */
export function WorkflowInvocations({ id }: { id: string }): JSX.Element | null {
    const { workflow } = useValues(workflowLogic)

    if (workflow?.trigger?.type === 'batch') {
        return <WorkflowBatchInvocations id={id} />
    }

    return (
        <HogInvocations
            id={id}
            functionKind="hog_flow"
            renderLogMessage={workflow ? (m) => renderWorkflowLogMessage(workflow, m) : undefined}
        />
    )
}
