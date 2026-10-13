import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'

import { getWorkflowTreeBranchSummary, type WorkflowTreePath } from './workflowTreePresentation'

export function HogFlowTreeFocusHeader({
    focusedPath,
    onReturnToWorkflow,
}: {
    focusedPath: WorkflowTreePath[]
    onReturnToWorkflow: () => void
}): JSX.Element | null {
    const focused = focusedPath.at(-1)
    if (!focused) {
        return null
    }
    return (
        <LemonCard hoverEffect={false} className="mb-3 p-3">
            <LemonButton
                type="tertiary"
                size="small"
                onClick={onReturnToWorkflow}
                id="workflow-tree-exit-focus"
                data-attr="workflow-tree-exit-focus"
            >
                Back to workflow
            </LemonButton>
            <p className="my-2 break-words text-xs text-secondary">
                {focusedPath.map(({ node, branch }) => `${node.action.name} › ${branch.label}`).join(' › ')}
            </p>
            <h3 className="mb-1 break-words">{focused.branch.label}</h3>
            <p className="mb-0 break-words text-xs text-secondary">
                {getWorkflowTreeBranchSummary(focused.node, focused.branch)}
            </p>
        </LemonCard>
    )
}
