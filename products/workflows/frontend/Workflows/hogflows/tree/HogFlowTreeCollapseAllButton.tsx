import { IconCollapse, IconExpand } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import type { WorkflowTreeSequence } from './workflowTree'
import {
    areAllWorkflowTreeBranchesCollapsed,
    getWorkflowTreeBranchGroups,
    type WorkflowTreeNodeViewState,
} from './workflowTreePresentation'

export function HogFlowTreeCollapseAllButton({
    tree,
    viewStates,
    onViewStateChange,
    onCollapsedChange,
}: {
    tree: WorkflowTreeSequence
    viewStates: Record<string, WorkflowTreeNodeViewState>
    onViewStateChange: (key: string, state: WorkflowTreeNodeViewState) => void
    onCollapsedChange: (collapsed: boolean) => void
}): JSX.Element | null {
    const groups = getWorkflowTreeBranchGroups(tree)
    if (!groups.length) {
        return null
    }

    // Reading the state back from the branches keeps the label right after someone expands one by hand.
    const allCollapsed = areAllWorkflowTreeBranchesCollapsed(groups, viewStates)

    return (
        <div className="mb-2 flex justify-end">
            <LemonButton
                type="tertiary"
                size="xsmall"
                icon={allCollapsed ? <IconExpand /> : <IconCollapse />}
                onClick={() => {
                    const nextCollapsed = !allCollapsed
                    for (const group of groups) {
                        onViewStateChange(group.occurrenceKey, {
                            branchesOpen: true,
                            collapsedBranches: nextCollapsed ? new Set(group.branchKeys) : new Set(),
                        })
                    }
                    onCollapsedChange(nextCollapsed)
                }}
                data-attr="workflow-tree-collapse-all-paths"
            >
                {allCollapsed ? 'Expand all paths' : 'Collapse all paths'}
            </LemonButton>
        </div>
    )
}
