import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'
import type { CSSProperties, ReactNode } from 'react'

import { IconArrowRight, IconChevronDown, IconEllipsis, IconWarning } from '@posthog/icons'

import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, type LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'

import { workflowLogic } from '../../workflowLogic'
import { getHogFlowBranchColor, useHogFlowBranchSelection } from '../HogFlowBranchSelection'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import type { HogFlowEdge } from '../types'
import { HogFlowTreeBranchConnector } from './HogFlowTreeBranchConnector'
import type { WorkflowTreeBranch, WorkflowTreeNode, WorkflowTreeSequence } from './workflowTree'
import {
    getWorkflowTreeBranchBadge,
    getWorkflowTreeBranchBadgeStyle,
    getWorkflowTreeBranchIndex,
    getWorkflowTreeBranchSummary,
    getWorkflowTreeNestedPathCount,
    getWorkflowTreePathHeaderId,
    getWorkflowTreeStepIds,
} from './workflowTreePresentation'

// A drag that rests on a closed path opens the path, so a step can be dropped inside it without a
// click. The grace period tells a drag that still hovers apart from one that left the header.
const DRAG_OPEN_DELAY_MS = 600
const DRAG_OPEN_GRACE_MS = 150

export function HogFlowTreeBranch({
    node,
    branch,
    index,
    isLast,
    branchCollapsed,
    onToggleCollapsed,
    onFocusBranch,
    onSelectContinuation,
    onSetPathsHidden,
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
    onSetPathsHidden?: (sequence: WorkflowTreeSequence, path: HogFlowEdge[], hidden: boolean) => void
    path: HogFlowEdge[]
    children: ReactNode
}): JSX.Element {
    const { setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { selectedBranch, setSelectedBranch } = useHogFlowBranchSelection()
    const dragOpenTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
    const lastDragOverAt = useRef(0)
    const joinAction = node.joinAction
    const branchIndex = getWorkflowTreeBranchIndex(branch, index)
    const pathColor = getHogFlowBranchColor(branchIndex)
    const branchPath = [...path, branch.edge]
    const isBranchSelected = selectedBranch?.actionId === node.action.id && selectedBranch.index === branchIndex
    const branchFilters =
        branchIndex !== null && node.action.type === 'conditional_branch'
            ? (node.action.config.conditions[branchIndex]?.filters.properties ?? [])
            : []
    const stepsNeedingAttention = branchCollapsed
        ? [...getWorkflowTreeStepIds(branch.sequence)].filter((stepId) => {
              const validationResult = actionValidationErrorsById[stepId]
              return validationResult?.valid === false || Object.keys(validationResult?.warnings ?? {}).length > 0
          }).length
        : 0

    useEffect(
        () => () => {
            if (dragOpenTimer.current) {
                clearTimeout(dragOpenTimer.current)
            }
        },
        []
    )

    const onHeaderDragOver = (): void => {
        lastDragOverAt.current = Date.now()
        if (!branchCollapsed || dragOpenTimer.current) {
            return
        }
        dragOpenTimer.current = setTimeout(() => {
            dragOpenTimer.current = null
            if (Date.now() - lastDragOverAt.current < DRAG_OPEN_GRACE_MS) {
                onToggleCollapsed()
            }
        }, DRAG_OPEN_DELAY_MS)
    }

    const selectContinuation = (): void => {
        if (joinAction) {
            setSelectedBranch(null)
            setSelectedNodeId(joinAction.id)
            onSelectContinuation(joinAction.id, path)
        }
    }

    const menuItems: LemonMenuItem[] = []
    if (
        onFocusBranch &&
        (branch.sequence.nodes.length > 1 || branch.sequence.nodes.some((child) => child.branches.length > 0))
    ) {
        menuItems.push({ label: 'Focus on this path', onClick: () => onFocusBranch(branchPath) })
    }
    if (onSetPathsHidden && getWorkflowTreeNestedPathCount(branch.sequence) > 0) {
        menuItems.push(
            { label: 'Show all paths inside', onClick: () => onSetPathsHidden(branch.sequence, branchPath, false) },
            { label: 'Hide all paths inside', onClick: () => onSetPathsHidden(branch.sequence, branchPath, true) }
        )
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
                    onDragOver={onHeaderDragOver}
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
                                id={getWorkflowTreePathHeaderId(node.action.id, branchPath)}
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
                                        style={getWorkflowTreeBranchBadgeStyle(node, pathColor)}
                                    >
                                        {getWorkflowTreeBranchBadge(node, branchIndex)}
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
                            <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                                <p className="mb-0 break-words text-xs text-secondary">
                                    {getWorkflowTreeBranchSummary(node, branch)}
                                </p>
                                {stepsNeedingAttention > 0 && (
                                    <LemonTag
                                        size="small"
                                        className="shrink-0"
                                        icon={<IconWarning className="text-warning" />}
                                    >
                                        {stepsNeedingAttention === 1
                                            ? '1 step needs attention'
                                            : `${stepsNeedingAttention} steps need attention`}
                                    </LemonTag>
                                )}
                            </div>
                        )}
                    </div>
                    {menuItems.length > 0 && (
                        <LemonMenu items={menuItems}>
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
