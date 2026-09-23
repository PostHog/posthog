import { useActions } from 'kea'
import type { ReactNode } from 'react'

import { IconChevronRight } from '@posthog/icons'

import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'

import { getHogFlowBranchColor, useHogFlowBranchSelection } from '../HogFlowBranchSelection'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import type { HogFlowEdge } from '../types'
import type { WorkflowTreeNode } from './workflowTree'
import {
    getWorkflowTreeBranchBadge,
    getWorkflowTreeBranchBadgeStyle,
    getWorkflowTreeBranchIndex,
    getWorkflowTreeBranchKey,
    getWorkflowTreeBranchSummary,
    getWorkflowTreePathHeaderId,
} from './workflowTreePresentation'

export function HogFlowTreeSubflowCard({
    node,
    path,
    step,
    onOpenPath,
}: {
    node: WorkflowTreeNode
    path: HogFlowEdge[]
    step: ReactNode
    onOpenPath: (path: HogFlowEdge[]) => void
}): JSX.Element {
    const { setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const { selectedBranch, setSelectedBranch } = useHogFlowBranchSelection()

    return (
        <div className="min-w-0" data-workflow-tree-subflow={node.action.id}>
            {step}
            <ul
                className="m-0 ms-4 flex min-w-0 flex-col gap-1 border-s-2 border-[var(--border-bold-3000)] ps-3 pt-2"
                data-attr="workflow-tree-subflow-paths"
            >
                {node.branches.map((branch, position) => {
                    const branchIndex = getWorkflowTreeBranchIndex(branch, position)
                    const pathColor = getHogFlowBranchColor(branchIndex)
                    const branchPath = [...path, branch.edge]
                    const isSelected =
                        selectedBranch?.actionId === node.action.id && selectedBranch.index === branchIndex
                    const branchFilters =
                        branchIndex !== null && node.action.type === 'conditional_branch'
                            ? (node.action.config.conditions[branchIndex]?.filters.properties ?? [])
                            : []
                    return (
                        <li
                            key={getWorkflowTreeBranchKey(branch.edge)}
                            className={cn(
                                'flex min-w-0 list-none flex-wrap items-center gap-x-2 gap-y-1 rounded border bg-card px-2 py-1',
                                isSelected && 'ring-1 ring-primary'
                            )}
                            data-workflow-branch-index={branchIndex ?? 'continue'}
                        >
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                className="!px-0 min-w-0 max-w-full"
                                aria-label={`Edit ${branch.label} path from ${node.action.name}`}
                                aria-pressed={isSelected}
                                id={getWorkflowTreePathHeaderId(node.action.id, branchPath)}
                                onClick={() => {
                                    setSelectedNodeId(node.action.id)
                                    setSelectedBranch({ actionId: node.action.id, index: branchIndex })
                                }}
                                data-attr="workflow-tree-select-branch"
                            >
                                <span className="flex min-w-0 flex-wrap items-center gap-2">
                                    <LemonTag
                                        size={node.action.type === 'conditional_branch' ? 'medium' : 'small'}
                                        className={cn(
                                            'shrink-0',
                                            node.action.type === 'conditional_branch' && 'uppercase'
                                        )}
                                        style={getWorkflowTreeBranchBadgeStyle(node, pathColor)}
                                    >
                                        {getWorkflowTreeBranchBadge(node, branchIndex)}
                                    </LemonTag>
                                    <span className="break-words whitespace-normal">{branch.label}</span>
                                </span>
                            </LemonButton>
                            {branchFilters.length > 0 && (
                                <div className="pointer-events-none min-w-0 max-w-full text-xs">
                                    <PropertyFiltersDisplay filters={branchFilters} compact />
                                </div>
                            )}
                            <span className="ms-auto min-w-0 break-words text-xs text-secondary">
                                {getWorkflowTreeBranchSummary(node, branch)}
                            </span>
                            <LemonButton
                                type="secondary"
                                size="xsmall"
                                className="shrink-0"
                                sideIcon={<IconChevronRight />}
                                aria-label={`Open ${branch.label} path`}
                                onClick={() => onOpenPath(branchPath)}
                                data-attr="workflow-tree-open-path"
                            >
                                Open
                            </LemonButton>
                        </li>
                    )
                })}
            </ul>
        </div>
    )
}
