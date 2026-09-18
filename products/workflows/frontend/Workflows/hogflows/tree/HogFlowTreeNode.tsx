import { useActions } from 'kea'
import { useEffect, useRef, useState } from 'react'
import type { DragEvent } from 'react'

import { IconArrowRight, IconChevronDown } from '@posthog/icons'

import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'

import { getHogFlowBranchColor, useHogFlowBranchSelection } from '../HogFlowBranchSelection'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import type { HogFlowEdge } from '../types'
import { HogFlowTreeDropzone } from './HogFlowTreeDropzone'
import { HogFlowTreeStep } from './HogFlowTreeStep'
import type { WorkflowTreeNode } from './workflowTree'
import { getWorkflowTreeBranchSummary } from './workflowTreePresentation'

const BRANCH_LIMIT = 6

export function HogFlowTreeNode({
    activeDropzones,
    draggedActionId,
    draggedActionIdRef,
    node,
    onDragEnd,
    onDragStart,
    branchColor,
    showIncomingConnector = true,
    onFocusBranch,
    onSelectContinuation,
}: {
    activeDropzones: boolean
    draggedActionId: string | null
    draggedActionIdRef: { current: string | null }
    node: WorkflowTreeNode
    onDragEnd: () => void
    onDragStart: (event: DragEvent<HTMLDivElement>, actionId: string, dragPreviewElement: HTMLDivElement | null) => void
    branchColor?: string
    showIncomingConnector?: boolean
    onFocusBranch?: (edge: HogFlowEdge) => void
    onSelectContinuation?: (actionId: string) => void
}): JSX.Element {
    const { setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const { selectedBranch, setSelectedBranch } = useHogFlowBranchSelection()
    const [branchesOpen, setBranchesOpen] = useState(true)
    const [collapsedBranches, setCollapsedBranches] = useState<Set<string>>(new Set())
    const [showAllBranches, setShowAllBranches] = useState(false)
    const nodeRef = useRef<HTMLDivElement>(null)
    const conditionBranches = node.branches.filter((branch) => branch.edge.type === 'branch')
    const visibleBranches = showAllBranches
        ? node.branches
        : [
              ...conditionBranches.slice(0, BRANCH_LIMIT),
              ...node.branches.filter((branch) => branch.edge.type === 'continue'),
          ]
    const hiddenBranchCount = node.branches.length - visibleBranches.length
    const joinEdge = node.joinEdges[0]
    const joinAction = node.joinAction
    const branchNoun = node.action.type === 'conditional_branch' ? 'conditions' : 'paths'

    const toggleBranchCollapsed = (branchKey: string): void => {
        setCollapsedBranches((current) => {
            const next = new Set(current)
            next.has(branchKey) ? next.delete(branchKey) : next.add(branchKey)
            return next
        })
    }

    const selectContinuation = (): void => {
        if (joinAction) {
            setSelectedBranch(null)
            setSelectedNodeId(joinAction.id)
            onSelectContinuation?.(joinAction.id)
            document.getElementById(`workflow-tree-step-${joinAction.id}`)?.scrollIntoView({ block: 'center' })
        }
    }

    useEffect(() => {
        if (selectedBranch?.actionId === node.action.id) {
            nodeRef.current
                ?.querySelector(`[data-workflow-branch-index="${selectedBranch.index ?? 'continue'}"]`)
                ?.scrollIntoView({ block: 'nearest' })
        }
    }, [node.action.id, selectedBranch])

    const step = (
        <HogFlowTreeStep
            action={node.action}
            branchColor={branchColor}
            collapseControl={
                node.branches.length > 0 ? (
                    <LemonButton
                        type="tertiary"
                        size="small"
                        className="!bg-transparent"
                        aria-label={`${branchesOpen ? 'Hide' : 'Show'} ${branchNoun}`}
                        aria-expanded={branchesOpen}
                        tooltip={`${branchesOpen ? 'Hide' : 'Show'} ${branchNoun}`}
                        icon={<IconChevronDown className={cn(!branchesOpen && '-rotate-90')} />}
                        onClick={() => setBranchesOpen((open) => !open)}
                    />
                ) : undefined
            }
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            canDrag={
                node.action.type !== 'trigger' &&
                node.action.type !== 'exit' &&
                (!node.branches.length || !!node.joinActionId)
            }
        />
    )

    return (
        <div ref={nodeRef} className="flex w-full min-w-0 flex-col">
            {node.incomingEdge && (
                <HogFlowTreeDropzone
                    active={activeDropzones}
                    draggedActionId={draggedActionId}
                    draggedActionIdRef={draggedActionIdRef}
                    onDragEnd={onDragEnd}
                    edge={node.incomingEdge}
                    showConnector={showIncomingConnector}
                    compact={!showIncomingConnector}
                />
            )}
            {node.branches.length === 0 ? (
                step
            ) : (
                <>
                    <LemonCard hoverEffect={false} className="p-2 min-w-0 bg-surface-secondary">
                        {step}
                        {branchesOpen && (
                            <div
                                className="flex min-w-0 flex-col gap-3 pt-3"
                                data-workflow-tree-branch-content={node.action.id}
                            >
                                {node.action.type === 'conditional_branch' && (
                                    <p className="mb-0 px-1 text-xs text-secondary">
                                        Conditions run from top to bottom. The first match sets the path.
                                    </p>
                                )}
                                {conditionBranches.length > BRANCH_LIMIT && (
                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        className="self-start"
                                        onClick={() => setShowAllBranches((showAll) => !showAll)}
                                        data-attr="workflow-tree-toggle-more-branches"
                                    >
                                        {showAllBranches
                                            ? 'Show fewer branches'
                                            : `Show ${hiddenBranchCount} more branches`}
                                    </LemonButton>
                                )}
                                {visibleBranches.map((branch, index) => {
                                    const branchIndex =
                                        branch.edge.type === 'branch' ? (branch.edge.index ?? index) : null
                                    const pathColor = getHogFlowBranchColor(branchIndex)
                                    const isBranchSelected =
                                        selectedBranch?.actionId === node.action.id &&
                                        selectedBranch.index === branchIndex
                                    const branchFilters =
                                        branchIndex !== null && node.action.type === 'conditional_branch'
                                            ? (node.action.config.conditions[branchIndex]?.filters.properties ?? [])
                                            : []
                                    const percentage =
                                        branchIndex !== null && node.action.type === 'random_cohort_branch'
                                            ? node.action.config.cohorts[branchIndex]?.percentage
                                            : undefined
                                    const branchKey = `${branch.edge.from}-${branch.edge.type}-${branch.edge.index ?? 'continue'}`
                                    const branchCollapsed = collapsedBranches.has(branchKey)
                                    const badge =
                                        node.action.type === 'conditional_branch'
                                            ? branchIndex === null
                                                ? 'Else'
                                                : `If #${branchIndex + 1}`
                                            : node.action.type === 'wait_until_condition'
                                              ? branchIndex === null
                                                  ? 'Timeout'
                                                  : 'Match'
                                              : branchIndex === null
                                                ? 'Fallback'
                                                : percentage !== undefined
                                                  ? `${percentage}%`
                                                  : `${branchIndex + 1}`

                                    return (
                                        <div
                                            key={branchKey}
                                            className="min-w-0"
                                            data-workflow-branch-index={branchIndex ?? 'continue'}
                                        >
                                            <LemonCard
                                                hoverEffect={false}
                                                focused={isBranchSelected}
                                                className="p-2 min-w-0"
                                            >
                                                <div className="flex min-w-0 items-start gap-2">
                                                    <LemonButton
                                                        type="tertiary"
                                                        size="xsmall"
                                                        className="!bg-transparent"
                                                        aria-label={`${branchCollapsed ? 'Show' : 'Hide'} branch steps`}
                                                        aria-expanded={!branchCollapsed}
                                                        icon={
                                                            <IconChevronDown
                                                                className={cn(branchCollapsed && '-rotate-90')}
                                                            />
                                                        }
                                                        onClick={() => toggleBranchCollapsed(branchKey)}
                                                    />
                                                    <div className="min-w-0 flex-1">
                                                        <LemonButton
                                                            type="tertiary"
                                                            size="xsmall"
                                                            fullWidth
                                                            className="!px-0"
                                                            aria-label={`Edit ${branch.label} path from ${node.action.name}`}
                                                            aria-pressed={isBranchSelected}
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
                                                                    size="small"
                                                                    style={{ color: pathColor, borderColor: pathColor }}
                                                                >
                                                                    {badge}
                                                                </LemonTag>
                                                                <span className="break-words whitespace-normal">
                                                                    {branch.label}
                                                                </span>
                                                            </span>
                                                        </LemonButton>
                                                        {branchFilters.length > 0 && (
                                                            <div className="pointer-events-none min-w-0 text-xs">
                                                                <PropertyFiltersDisplay
                                                                    filters={branchFilters}
                                                                    compact
                                                                />
                                                            </div>
                                                        )}
                                                        <p className="mb-0 mt-1 break-words text-xs text-secondary">
                                                            {getWorkflowTreeBranchSummary(node, branch)}
                                                        </p>
                                                        {onFocusBranch &&
                                                            (branch.sequence.nodes.length > 1 ||
                                                                branch.sequence.nodes.some(
                                                                    (child) => child.branches.length > 0
                                                                )) && (
                                                                <LemonButton
                                                                    type="tertiary"
                                                                    size="xsmall"
                                                                    className="!px-0"
                                                                    onClick={() => onFocusBranch(branch.edge)}
                                                                    data-attr="workflow-tree-focus-branch"
                                                                >
                                                                    Focus on this path
                                                                </LemonButton>
                                                            )}
                                                    </div>
                                                </div>
                                                <div
                                                    className={cn(
                                                        'min-w-0 border-l ps-3 ms-2 mt-2',
                                                        branchCollapsed && 'hidden'
                                                    )}
                                                    style={{ borderColor: pathColor }}
                                                >
                                                    {branch.sequence.nodes.length === 0 && (
                                                        <p className="mb-1 text-xs text-secondary">
                                                            No steps in this path
                                                        </p>
                                                    )}
                                                    {branch.sequence.nodes.map((childNode, childIndex) => (
                                                        <HogFlowTreeNode
                                                            key={childNode.action.id}
                                                            node={childNode}
                                                            activeDropzones={activeDropzones}
                                                            draggedActionId={draggedActionId}
                                                            draggedActionIdRef={draggedActionIdRef}
                                                            onDragStart={onDragStart}
                                                            onDragEnd={onDragEnd}
                                                            branchColor={pathColor}
                                                            showIncomingConnector={childIndex > 0}
                                                            onFocusBranch={onFocusBranch}
                                                            onSelectContinuation={onSelectContinuation}
                                                        />
                                                    ))}
                                                    {branch.sequence.trailingEdge && (
                                                        <HogFlowTreeDropzone
                                                            active={activeDropzones}
                                                            draggedActionId={draggedActionId}
                                                            draggedActionIdRef={draggedActionIdRef}
                                                            onDragEnd={onDragEnd}
                                                            edge={branch.sequence.trailingEdge}
                                                            showConnector={false}
                                                            insertionLabel={`Add step to ${branch.label}`}
                                                        />
                                                    )}
                                                    {joinAction && (
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
                                                    )}
                                                </div>
                                            </LemonCard>
                                        </div>
                                    )
                                })}
                            </div>
                        )}
                    </LemonCard>
                    {joinAction && (
                        <p className="mb-0 px-2 pt-2 break-words text-xs text-secondary">{`After ${node.action.name} · Continue to: ${joinAction.name}`}</p>
                    )}
                    {joinEdge && (
                        <HogFlowTreeDropzone
                            active={activeDropzones}
                            draggedActionId={draggedActionId}
                            draggedActionIdRef={draggedActionIdRef}
                            onDragEnd={onDragEnd}
                            edge={joinEdge}
                            isBranchJoin
                            joinEdges={node.joinEdges}
                            insertionLabel={`Add step after ${node.action.name} paths`}
                        />
                    )}
                </>
            )}
        </div>
    )
}
