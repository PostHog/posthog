import { useActions } from 'kea'
import { useEffect, useRef, useState } from 'react'
import type { DragEvent } from 'react'

import { IconArrowRight, IconChevronDown } from '@posthog/icons'

import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { Badge, Button, Item, ItemContent, ItemTitle, Text, cn } from 'lib/ui/quill'

import { getHogFlowBranchColor, useHogFlowBranchSelection } from '../HogFlowBranchSelection'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowTreeBranchIndicator } from './HogFlowTreeBranchIndicator'
import { HogFlowTreeDropzone } from './HogFlowTreeDropzone'
import { HogFlowTreeStep } from './HogFlowTreeStep'
import type { WorkflowTreeNode } from './workflowTree'

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
}: {
    activeDropzones: boolean
    draggedActionId: string | null
    draggedActionIdRef: { current: string | null }
    node: WorkflowTreeNode
    onDragEnd: () => void
    onDragStart: (event: DragEvent<HTMLDivElement>, actionId: string, dragPreviewElement: HTMLDivElement | null) => void
    branchColor?: string
    showIncomingConnector?: boolean
}): JSX.Element {
    const { setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const { selectedBranch, setSelectedBranch } = useHogFlowBranchSelection()
    const [branchesOpen, setBranchesOpen] = useState(true)
    const [collapsedBranches, setCollapsedBranches] = useState<Set<string>>(new Set())
    const [showAllBranches, setShowAllBranches] = useState(false)
    const nodeRef = useRef<HTMLDivElement>(null)
    const visibleBranches = showAllBranches ? node.branches : node.branches.slice(0, BRANCH_LIMIT)
    const hiddenBranchCount = node.branches.length - visibleBranches.length
    const joinEdge = node.joinEdges[0]
    const joinAction = node.joinAction
    const branchNoun = node.action.type === 'random_cohort_branch' ? 'paths' : 'conditions'
    const toggleBranchCollapsed = (branchKey: string): void => {
        setCollapsedBranches((current) => {
            const next = new Set(current)
            next.has(branchKey) ? next.delete(branchKey) : next.add(branchKey)
            return next
        })
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
                    <Tooltip title={`${branchesOpen ? 'Hide' : 'Show'} ${branchNoun}`}>
                        <Button
                            type="button"
                            variant="default"
                            size="icon"
                            aria-label={`${branchesOpen ? 'Hide' : 'Show'} ${branchNoun}`}
                            onClick={() => setBranchesOpen((open) => !open)}
                        >
                            <IconChevronDown
                                className={cn('size-5 transition-transform', !branchesOpen && '-rotate-90')}
                            />
                        </Button>
                    </Tooltip>
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
        <div ref={nodeRef} className="flex w-full flex-col">
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
                    {step}
                    {branchesOpen && (
                        <div className="flex flex-col gap-3 pt-2">
                            {visibleBranches.map((branch, index) => {
                                const branchIndex = branch.edge.type === 'branch' ? (branch.edge.index ?? index) : null
                                const branchColor = getHogFlowBranchColor(branchIndex)
                                const isBranchSelected =
                                    selectedBranch?.actionId === node.action.id && selectedBranch.index === branchIndex
                                const branchFilters =
                                    branchIndex !== null && node.action.type === 'conditional_branch'
                                        ? (node.action.config.conditions[branchIndex]?.filters.properties ?? [])
                                        : []
                                const cohortPercentage =
                                    branchIndex !== null && node.action.type === 'random_cohort_branch'
                                        ? node.action.config.cohorts[branchIndex]?.percentage
                                        : undefined

                                const branchKey = `${branch.edge.from}-${branch.edge.type}-${branch.edge.index ?? 'continue'}`
                                const branchCollapsed = collapsedBranches.has(branchKey)
                                const hiddenStepCount = branch.sequence.nodes.length

                                return (
                                    <div
                                        key={branchKey}
                                        className="relative flex min-w-0 flex-col ps-0"
                                        data-workflow-branch-index={branchIndex ?? 'continue'}
                                    >
                                        <Item
                                            variant="outline"
                                            size="xs"
                                            className="relative z-10 flex-nowrap bg-card text-start"
                                            style={{
                                                borderColor: branchColor,
                                                borderWidth: isBranchSelected ? 2 : undefined,
                                            }}
                                            data-attr="workflow-tree-select-branch"
                                        >
                                            <Button
                                                type="button"
                                                variant="link"
                                                className="absolute inset-0 z-0 h-full w-full"
                                                aria-label={`Edit ${branch.label} path from ${node.action.name}`}
                                                aria-pressed={isBranchSelected}
                                                onClick={() => {
                                                    setSelectedNodeId(node.action.id)
                                                    setSelectedBranch({ actionId: node.action.id, index: branchIndex })
                                                }}
                                            />
                                            <Badge
                                                variant="default"
                                                className="pointer-events-none relative z-10 font-mono text-xxs"
                                                style={{ color: branchColor, borderColor: branchColor }}
                                            >
                                                {branch.edge.type === 'continue' ? 'ELSE' : 'IF'}
                                            </Badge>
                                            <ItemContent className="pointer-events-none relative z-10 min-w-0">
                                                <ItemTitle className="max-w-full truncate text-xs">
                                                    {branch.label}
                                                </ItemTitle>
                                            </ItemContent>
                                            {branchFilters.length > 0 && (
                                                <div className="pointer-events-none relative z-10 ms-auto min-w-0 max-w-[60%] overflow-hidden [&_.PropertyFilterButton]:!gap-1 [&_.PropertyFilterButton]:!px-1.5 [&_.PropertyFilterButton]:!py-px [&_.PropertyFilterButton]:!text-xs [&_.PropertyFilterButton>_.LemonIcon]:!text-xs">
                                                    <PropertyFiltersDisplay filters={branchFilters} compact />
                                                </div>
                                            )}
                                            {cohortPercentage !== undefined && (
                                                <Text
                                                    size="xs"
                                                    variant="muted"
                                                    render={<span />}
                                                    className="pointer-events-none relative z-10 ms-auto shrink-0"
                                                >
                                                    {cohortPercentage}%
                                                </Text>
                                            )}
                                            <div className="relative z-20 ms-auto flex shrink-0 items-center gap-1">
                                                <Tooltip title={`${branchCollapsed ? 'Show' : 'Hide'} branch steps`}>
                                                    <Button
                                                        type="button"
                                                        variant="default"
                                                        size="xs"
                                                        className={cn(
                                                            !(branchCollapsed && hiddenStepCount > 0) && '!w-5 !px-0'
                                                        )}
                                                        aria-label={`${branchCollapsed ? 'Show' : 'Hide'} branch steps`}
                                                        onClick={() => toggleBranchCollapsed(branchKey)}
                                                    >
                                                        {branchCollapsed &&
                                                            hiddenStepCount > 0 &&
                                                            `${hiddenStepCount} ${hiddenStepCount === 1 ? 'step' : 'steps'} hidden`}
                                                        <IconChevronDown
                                                            className={cn(
                                                                'size-4 transition-transform',
                                                                branchCollapsed && '-rotate-90'
                                                            )}
                                                        />
                                                    </Button>
                                                </Tooltip>
                                            </div>
                                        </Item>
                                        <div className={cn('flex flex-col ps-8', branchCollapsed && 'hidden')}>
                                            {branch.sequence.nodes.length === 0 && (
                                                <div className="relative">
                                                    <HogFlowTreeBranchIndicator
                                                        color={branchColor}
                                                        className="inset-y-2"
                                                    />
                                                    <Text size="xs" variant="muted" className="py-2">
                                                        No steps in this branch.
                                                    </Text>
                                                </div>
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
                                                    branchColor={branchColor}
                                                    showIncomingConnector={childIndex > 0}
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
                                                    compact
                                                />
                                            )}
                                            {joinAction && (
                                                <div className="relative flex items-center gap-1">
                                                    <HogFlowTreeBranchIndicator
                                                        color={branchColor}
                                                        className="inset-y-1"
                                                    />
                                                    <Text size="xxs" variant="muted" render={<span />}>
                                                        {node.action.type === 'random_cohort_branch'
                                                            ? 'End of cohort split · continues to'
                                                            : 'End of condition · continues to'}
                                                    </Text>
                                                    <Button
                                                        type="button"
                                                        variant="link"
                                                        size="xs"
                                                        className="min-w-0 max-w-56 px-0"
                                                        onClick={() => {
                                                            setSelectedBranch(null)
                                                            setSelectedNodeId(joinAction.id)
                                                            document
                                                                .getElementById(`workflow-tree-step-${joinAction.id}`)
                                                                ?.scrollIntoView({
                                                                    behavior: 'smooth',
                                                                    block: 'center',
                                                                })
                                                        }}
                                                        data-attr="workflow-tree-select-continuation"
                                                    >
                                                        <span className="truncate">{joinAction.name}</span>
                                                        <IconArrowRight className="size-3" />
                                                    </Button>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                )
                            })}
                            {node.branches.length > BRANCH_LIMIT && (
                                <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    className="self-start border-dashed"
                                    onClick={() => setShowAllBranches((showAll) => !showAll)}
                                    data-attr="workflow-tree-toggle-more-branches"
                                >
                                    {showAllBranches
                                        ? 'Show fewer branches'
                                        : `Show ${hiddenBranchCount} more branches`}
                                </Button>
                            )}
                        </div>
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
                        />
                    )}
                </>
            )}
        </div>
    )
}
