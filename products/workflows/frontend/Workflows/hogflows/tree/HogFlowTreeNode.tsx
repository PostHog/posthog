import { useActions } from 'kea'
import { useEffect, useRef, useState } from 'react'
import type { DragEvent } from 'react'

import { IconArrowRight } from '@posthog/icons'

import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import {
    Badge,
    Button,
    Collapsible,
    CollapsibleContent,
    CollapsibleHeader,
    CollapsibleTrigger,
    Item,
    ItemContent,
    ItemTitle,
    Separator,
    Text,
} from 'lib/ui/quill'

import { getHogFlowBranchColor, getHogFlowBranchTint, useHogFlowBranchSelection } from '../HogFlowBranchSelection'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowTreeDropzone } from './HogFlowTreeDropzone'
import { HogFlowTreeStep } from './HogFlowTreeStep'
import type { WorkflowTreeNode } from './workflowTree'

const BRANCH_LIMIT = 6
export function HogFlowTreeNode({
    activeDropzones,
    draggedActionId,
    node,
    onDragEnd,
    onDragStart,
    showIncomingConnector = true,
}: {
    activeDropzones: boolean
    draggedActionId: string | null
    node: WorkflowTreeNode
    onDragEnd: () => void
    onDragStart: (event: DragEvent<HTMLDivElement>, actionId: string) => void
    showIncomingConnector?: boolean
}): JSX.Element {
    const { setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const { selectedBranch, setSelectedBranch } = useHogFlowBranchSelection()
    const [branchesOpen, setBranchesOpen] = useState(true)
    const [showAllBranches, setShowAllBranches] = useState(false)
    const nodeRef = useRef<HTMLDivElement>(null)
    const visibleBranches = showAllBranches ? node.branches : node.branches.slice(0, BRANCH_LIMIT)
    const hiddenBranchCount = node.branches.length - visibleBranches.length
    const joinEdge = node.joinEdges[0]
    const joinAction = node.joinAction
    const branchNoun = node.action.type === 'random_cohort_branch' ? 'paths' : 'conditions'

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
            dragged={draggedActionId === node.action.id}
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
                    edge={node.incomingEdge}
                    showConnector={showIncomingConnector}
                    compact={!showIncomingConnector}
                />
            )}
            {node.branches.length === 0 ? (
                step
            ) : (
                <Collapsible variant="folder" open={branchesOpen} onOpenChange={setBranchesOpen}>
                    <CollapsibleHeader>{step}</CollapsibleHeader>
                    <div className="flex">
                        <CollapsibleTrigger className="ms-10 -mt-px h-6 w-auto rounded-t-none border border-border bg-card px-2 text-xxs">
                            {`${branchesOpen ? 'Hide' : 'Show'} ${branchNoun}`}
                        </CollapsibleTrigger>
                    </div>
                    <CollapsibleContent className="flex flex-col gap-3 pt-2">
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

                            return (
                                <div
                                    key={`${branch.edge.from}-${branch.edge.type}-${branch.edge.index ?? 'continue'}`}
                                    className="relative flex min-w-0 flex-col ps-0"
                                    data-workflow-branch-index={branchIndex ?? 'continue'}
                                >
                                    <div
                                        aria-hidden="true"
                                        className={`pointer-events-none absolute bottom-0 start-0 top-2 ${isBranchSelected ? 'w-0.5' : 'w-px'}`}
                                        style={{ backgroundColor: branchColor }}
                                    />
                                    <Item
                                        render={<button type="button" />}
                                        variant="muted"
                                        size="xs"
                                        className="relative z-10 flex-nowrap rounded-bl-none text-start"
                                        style={{
                                            borderColor: branchColor,
                                            borderWidth: isBranchSelected ? 2 : undefined,
                                            backgroundColor: isBranchSelected
                                                ? getHogFlowBranchTint(branchIndex)
                                                : undefined,
                                        }}
                                        aria-label={`Edit ${branch.label} path from ${node.action.name}`}
                                        aria-pressed={isBranchSelected}
                                        onClick={() => {
                                            setSelectedNodeId(node.action.id)
                                            setSelectedBranch({ actionId: node.action.id, index: branchIndex })
                                        }}
                                        data-attr="workflow-tree-select-branch"
                                    >
                                        <Badge
                                            variant="default"
                                            className="font-mono text-xxs"
                                            style={{ color: branchColor, borderColor: branchColor }}
                                        >
                                            {branch.edge.type === 'continue' ? 'ELSE' : 'IF'}
                                        </Badge>
                                        <ItemContent className="min-w-0">
                                            <ItemTitle className="max-w-full truncate text-xs">
                                                {branch.label}
                                            </ItemTitle>
                                        </ItemContent>
                                        {branchFilters.length > 0 && (
                                            <div className="ms-auto min-w-0 max-w-[60%] overflow-hidden [&_.PropertyFilterButton]:!gap-1 [&_.PropertyFilterButton]:!px-1.5 [&_.PropertyFilterButton]:!py-px [&_.PropertyFilterButton]:!text-xs [&_.PropertyFilterButton>_.LemonIcon]:!text-xs">
                                                <PropertyFiltersDisplay filters={branchFilters} compact />
                                            </div>
                                        )}
                                        {cohortPercentage !== undefined && (
                                            <Text
                                                size="xs"
                                                variant="muted"
                                                render={<span />}
                                                className="ms-auto shrink-0"
                                            >
                                                {cohortPercentage}%
                                            </Text>
                                        )}
                                    </Item>
                                    <div className="flex flex-col ps-3">
                                        {branch.sequence.nodes.length === 0 && (
                                            <Text size="xs" variant="muted" className="py-2">
                                                No steps in this branch.
                                            </Text>
                                        )}
                                        {branch.sequence.nodes.map((childNode, childIndex) => (
                                            <HogFlowTreeNode
                                                key={childNode.action.id}
                                                node={childNode}
                                                activeDropzones={activeDropzones}
                                                draggedActionId={draggedActionId}
                                                onDragStart={onDragStart}
                                                onDragEnd={onDragEnd}
                                                showIncomingConnector={childIndex > 0}
                                            />
                                        ))}
                                        {branch.sequence.trailingEdge && (
                                            <HogFlowTreeDropzone
                                                active={activeDropzones}
                                                draggedActionId={draggedActionId}
                                                edge={branch.sequence.trailingEdge}
                                                showConnector={false}
                                                compact
                                            />
                                        )}
                                        {joinAction && (
                                            <div className="flex items-center gap-1">
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
                                                            ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
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
                                {showAllBranches ? 'Show fewer branches' : `Show ${hiddenBranchCount} more branches`}
                            </Button>
                        )}
                    </CollapsibleContent>
                    {joinEdge && (
                        <>
                            <Separator className="mx-3 my-1 hidden group-data-[open]/collapsible:block" />
                            <HogFlowTreeDropzone
                                active={activeDropzones}
                                draggedActionId={draggedActionId}
                                edge={joinEdge}
                                isBranchJoin
                                joinEdges={node.joinEdges}
                            />
                        </>
                    )}
                </Collapsible>
            )}
        </div>
    )
}
