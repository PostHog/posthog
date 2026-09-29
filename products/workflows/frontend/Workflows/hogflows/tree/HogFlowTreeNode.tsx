import { Fragment, useEffect, useRef } from 'react'
import type { DragEvent } from 'react'

import { IconChevronDown } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { cn } from 'lib/utils/css-classes'

import { useHogFlowBranchSelection } from '../HogFlowBranchSelection'
import type { HogFlowEdge } from '../types'
import { HogFlowTreeBranch } from './HogFlowTreeBranch'
import { HogFlowTreeDropzone } from './HogFlowTreeDropzone'
import { HogFlowTreeStep } from './HogFlowTreeStep'
import type { WorkflowTreeNode } from './workflowTree'
import {
    getWorkflowTreeOccurrenceKey,
    getWorkflowTreeStepId,
    WORKFLOW_TREE_BRANCH_LIMIT,
    type WorkflowTreeNodeViewState,
} from './workflowTreePresentation'

export function HogFlowTreeNode({
    activeDropzones,
    draggedActionId,
    draggedActionIdRef,
    node,
    onDragEnd,
    onDragStart,
    showIncomingConnector = true,
    onFocusBranch,
    onSelectContinuation,
    path,
    viewStates,
    onViewStateChange,
}: {
    activeDropzones: boolean
    draggedActionId: string | null
    draggedActionIdRef: { current: string | null }
    node: WorkflowTreeNode
    onDragEnd: () => void
    onDragStart: (event: DragEvent<HTMLDivElement>, actionId: string, dragPreviewElement: HTMLDivElement | null) => void
    showIncomingConnector?: boolean
    onFocusBranch?: (path: HogFlowEdge[]) => void
    onSelectContinuation: (actionId: string, path: HogFlowEdge[]) => void
    path: HogFlowEdge[]
    viewStates: Record<string, WorkflowTreeNodeViewState>
    onViewStateChange: (key: string, state: WorkflowTreeNodeViewState) => void
}): JSX.Element {
    const { selectedBranch } = useHogFlowBranchSelection()
    const occurrenceKey = getWorkflowTreeOccurrenceKey(node.action.id, path)
    const {
        branchesOpen = true,
        collapsedBranches = new Set<string>(),
        showAllBranches = false,
    } = viewStates[occurrenceKey] ?? {}
    const nodeRef = useRef<HTMLDivElement>(null)
    const branchContentRef = useRef<HTMLDivElement>(null)
    const branchToggleRef = useRef<HTMLButtonElement>(null)
    const pendingBranchToggle = useRef(false)
    const conditionBranches = node.branches.filter((branch) => branch.edge.type === 'branch')
    const visibleBranches = showAllBranches
        ? node.branches
        : [
              ...conditionBranches.slice(0, WORKFLOW_TREE_BRANCH_LIMIT),
              ...node.branches.filter((branch) => branch.edge.type === 'continue'),
          ]
    const hiddenBranchCount = node.branches.length - visibleBranches.length
    const visibleConditionCount = showAllBranches ? conditionBranches.length : WORKFLOW_TREE_BRANCH_LIMIT
    const firstHiddenBranchIndex = conditionBranches[WORKFLOW_TREE_BRANCH_LIMIT]?.edge.index
    const joinEdge = node.joinEdges[0]
    const branchNoun = node.action.type === 'conditional_branch' ? 'conditions' : 'paths'

    const toggleBranchCollapsed = (branchKey: string): void => {
        const next = new Set(collapsedBranches)
        next.has(branchKey) ? next.delete(branchKey) : next.add(branchKey)
        onViewStateChange(occurrenceKey, { collapsedBranches: next })
    }

    useEffect(() => {
        if (!pendingBranchToggle.current) {
            return
        }
        pendingBranchToggle.current = false
        const target = showAllBranches
            ? branchContentRef.current?.querySelector<HTMLButtonElement>(
                  `:scope > [data-workflow-branch-index="${firstHiddenBranchIndex}"] [data-attr="workflow-tree-select-branch"]`
              )
            : branchToggleRef.current
        target?.focus({ preventScroll: true })
        target?.scrollIntoView({ block: showAllBranches ? 'start' : 'nearest' })
    }, [showAllBranches, firstHiddenBranchIndex])

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
            stepId={getWorkflowTreeStepId(node.action.id, path)}
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
                        onClick={() => onViewStateChange(occurrenceKey, { branchesOpen: !branchesOpen })}
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
                    <div className="min-w-0">
                        {step}
                        {branchesOpen && (
                            <div
                                ref={branchContentRef}
                                className="flex min-w-0 flex-col gap-3 pt-3"
                                data-workflow-tree-branch-content={node.action.id}
                            >
                                {visibleBranches.map((branch, index) => {
                                    const branchKey = `${branch.edge.from}-${branch.edge.type}-${branch.edge.index ?? 'continue'}`
                                    return (
                                        <Fragment key={branchKey}>
                                            <HogFlowTreeBranch
                                                node={node}
                                                branch={branch}
                                                index={index}
                                                isLast={index === visibleBranches.length - 1}
                                                branchCollapsed={collapsedBranches.has(branchKey)}
                                                onToggleCollapsed={() => toggleBranchCollapsed(branchKey)}
                                                onFocusBranch={onFocusBranch}
                                                onSelectContinuation={onSelectContinuation}
                                                path={path}
                                            >
                                                {branch.sequence.nodes.map((childNode, childIndex) => (
                                                    <HogFlowTreeNode
                                                        key={childNode.action.id}
                                                        node={childNode}
                                                        activeDropzones={activeDropzones}
                                                        draggedActionId={draggedActionId}
                                                        draggedActionIdRef={draggedActionIdRef}
                                                        onDragStart={onDragStart}
                                                        onDragEnd={onDragEnd}
                                                        showIncomingConnector={childIndex > 0}
                                                        onFocusBranch={onFocusBranch}
                                                        onSelectContinuation={onSelectContinuation}
                                                        path={[...path, branch.edge]}
                                                        viewStates={viewStates}
                                                        onViewStateChange={onViewStateChange}
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
                                                        alwaysVisible={branch.sequence.nodes.length === 0}
                                                        insertionLabel={`Add step to ${branch.label}`}
                                                    />
                                                )}
                                            </HogFlowTreeBranch>
                                            {conditionBranches.length > WORKFLOW_TREE_BRANCH_LIMIT &&
                                                index === visibleConditionCount - 1 && (
                                                    <div className="relative ps-8">
                                                        {index < visibleBranches.length - 1 && (
                                                            <span
                                                                aria-hidden="true"
                                                                className="pointer-events-none absolute start-2 -top-3 -bottom-3 border-s-2 border-[var(--border-bold-3000)]"
                                                            />
                                                        )}
                                                        <LemonButton
                                                            ref={branchToggleRef}
                                                            type="secondary"
                                                            size="xsmall"
                                                            aria-expanded={showAllBranches}
                                                            onClick={() => {
                                                                pendingBranchToggle.current = true
                                                                onViewStateChange(occurrenceKey, {
                                                                    showAllBranches: !showAllBranches,
                                                                })
                                                            }}
                                                            data-attr="workflow-tree-toggle-more-branches"
                                                        >
                                                            {showAllBranches
                                                                ? 'Show fewer branches'
                                                                : `Show ${hiddenBranchCount} more branches`}
                                                        </LemonButton>
                                                    </div>
                                                )}
                                        </Fragment>
                                    )
                                })}
                            </div>
                        )}
                    </div>
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
