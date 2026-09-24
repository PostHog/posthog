import type { WorkflowTreeUnreachableStep } from './hogflows/tree/workflowTree'
import { getWorkflowTreeUnreachableStepFix } from './hogflows/tree/workflowTreePresentation'

const LIST_VIEW_UNREACHABLE_STEP_LIMIT = 5

export function ListViewDisabledReason({ steps }: { steps: WorkflowTreeUnreachableStep[] }): JSX.Element {
    const hiddenCount = steps.length - LIST_VIEW_UNREACHABLE_STEP_LIMIT
    return (
        <div className="max-w-80">
            <div>Some steps cannot be shown in list view. Fix these steps in graph view first:</div>
            <ul className="list-disc pl-4 mt-1 space-y-1">
                {steps.slice(0, LIST_VIEW_UNREACHABLE_STEP_LIMIT).map((step) => (
                    <li key={step.action.id}>
                        <strong>{step.action.name}</strong>: {getWorkflowTreeUnreachableStepFix(step)}
                    </li>
                ))}
                {hiddenCount > 0 && <li>And {hiddenCount} more</li>}
            </ul>
        </div>
    )
}
