import { useActions } from 'kea'
import type { CSSProperties, ReactNode } from 'react'

import { IconArrowRight, IconChevronDown, IconEllipsis } from '@posthog/icons'

import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'

import { getHogFlowBranchColor, useHogFlowBranchSelection } from '../HogFlowBranchSelection'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import type { HogFlowEdge } from '../types'
import { HogFlowTreeBranchConnector } from './HogFlowTreeBranchConnector'
import { getWaitTimeoutLabel, type WorkflowTreeBranch, type WorkflowTreeNode } from './workflowTree'
import { getWorkflowTreeBranchSummary, getWorkflowTreeOccurrenceKey } from './workflowTreePresentation'

export function HogFlowTreeBranch({
    node,
    branch,
    index,
    isLast,
    branchCollapsed,
    onToggleCollapsed,
    onFocusBranch,
    onSelectContinuation,
    path,
    children,
}: {
    node: WorkflowTreeNode
    branch: WorkflowTreeBranch
    index: number
    isLast: boolean
    branchCollapsed: boolean
    onToggleCollapsed: () => void
    onFocusBranch?: (path: HogFlowEdge[]) => void
    onSelectContinuation: (actionId: string, path: HogFlowEdge[]) => void
    path: HogFlowEdge[]
    children: ReactNode
}): JSX.Element {
    const { setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const { selectedBranch, setSelectedBranch } = useHogFlowBranchSelection()
    const joinAction = node.joinAction
    const branchIndex = branch.edge.type === 'branch' ? (branch.edge.index ?? index) : null
    const pathColor = getHogFlowBranchColor(branchIndex)
    const isBranchSelected = selectedBranch?.actionId === node.action.id && selectedBranch.index === branchIndex
    const branchFilters =
        branchIndex !== null && node.action.type === 'conditional_branch'
            ? (node.action.config.conditions[branchIndex]?.filters.properties ?? [])
            : []
    const percentage =
        branchIndex !== null && node.action.type === 'random_cohort_branch'
            ? node.action.config.cohorts[branchIndex]?.percentage
            : undefined
    const badge =
        node.action.type === 'conditional_branch'
            ? branchIndex === null
                ? 'Else'
                : `If #${branchIndex + 1}`
            : node.action.type === 'wait_until_condition'
              ? branchIndex === null
                  ? getWaitTimeoutLabel(node.action.config.max_wait_duration)
                      ? 'Timeout'
                      : 'No match'
                  : 'Match'
              : branchIndex === null
                ? 'Fallback'
                : percentage !== undefined
                  ? `${percentage}%`
                  : `${branchIndex + 1}`

    const selectContinuation = (): void => {
        if (joinAction) {
            setSelectedBranch(null)
            setSelectedNodeId(joinAction.id)
            onSelectContinuation(joinAction.id, path)
        }
    }

    return (
        <div
            className="relative min-w-0 ps-6 [--workflow-branch-line-color:var(--border-bold-3000)] has-[>[data-workflow-branch-highlight]>[data-workflow-branch-header]:is(:hover,:focus-within)]:[--workflow-branch-line-color:var(--workflow-branch-color)]"
            style={{ '--workflow-branch-color': pathColor } as CSSProperties}
            data-workflow-branch-index={branchIndex ?? 'continue'}
        >
            <HogFlowTreeBranchConnector isLast={isLast} />
            <div className="min-w-0" data-workflow-branch-highlight>
                <div
                    data-workflow-branch-header
                    className={cn(
                        'flex min-w-0 items-start gap-2 rounded p-2',
                        isBranchSelected && 'bg-surface-secondary ring-1 ring-primary'
                    )}
                >
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        className="!bg-transparent"
                        aria-label={`${branchCollapsed ? 'Show' : 'Hide'} branch steps`}
                        aria-expanded={!branchCollapsed}
                        icon={<IconChevronDown className={cn(branchCollapsed && '-rotate-90')} />}
                        onClick={() => onToggleCollapsed()}
                    />
                    <div className="min-w-0 flex-1">
                        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                className="!px-0 max-w-full"
                                aria-label={`Edit ${branch.label} path from ${node.action.name}`}
                                aria-pressed={isBranchSelected}
                                // A focused path returns focus here. Every branch header renders this
                                // button, but the actions menu below it is conditional.
                                id={`workflow-tree-path-${getWorkflowTreeOccurrenceKey(node.action.id, [...path, branch.edge])}`}
                                onClick={() => {
                                    setSelectedNodeId(node.action.id)
                                    setSelectedBranch({
                                        actionId: node.action.id,
                                        index: branchIndex,
                                    })
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
                                        style={{
                                            color:
                                                node.action.type === 'conditional_branch'
                                                    ? `color-mix(in srgb, ${pathColor} 60%, var(--text-3000))`
                                                    : pathColor,
                                            borderColor: pathColor,
                                        }}
                                    >
                                        {badge}
                                    </LemonTag>
                                    <span className="break-words whitespace-normal">{branch.label}</span>
                                </span>
                            </LemonButton>
                            {branchFilters.length > 0 && (
                                <div className="pointer-events-none ms-auto min-w-0 max-w-full text-xs">
                                    <PropertyFiltersDisplay filters={branchFilters} compact />
                                </div>
                            )}
                        </div>
                        {branchCollapsed && (
                            <p className="mb-0 mt-1 break-words text-xs text-secondary">
                                {getWorkflowTreeBranchSummary(node, branch)}
                            </p>
                        )}
                    </div>
                    {onFocusBranch &&
                        (branch.sequence.nodes.length > 1 ||
                            branch.sequence.nodes.some((child) => child.branches.length > 0)) && (
                            <LemonMenu
                                items={[
                                    {
                                        label: 'Focus on this path',
                                        onClick: () => onFocusBranch([...path, branch.edge]),
                                    },
                                ]}
                            >
                                <LemonButton
                                    type="tertiary"
                                    size="xsmall"
                                    className="!bg-transparent shrink-0"
                                    icon={<IconEllipsis />}
                                    aria-label={`Actions for ${branch.label}`}
                                    tooltip="Path actions"
                                    data-attr="workflow-tree-focus-branch"
                                />
                            </LemonMenu>
                        )}
                </div>
                <div className={cn('min-w-0 ps-3 ms-2 mt-2', branchCollapsed && 'hidden')}>
                    {children}
                    {joinAction && (
                        <div className="relative py-1">
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                className="!px-0"
                                icon={<IconArrowRight />}
                                onClick={selectContinuation}
                                data-attr="workflow-tree-select-continuation"
                            >
                                <span className="break-words whitespace-normal">{`Continue to: ${joinAction.name}`}</span>
                            </LemonButton>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
