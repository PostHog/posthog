import { useActions } from 'kea'
import { useEffect, useRef, useState } from 'react'
import type { DragEvent } from 'react'

import { IconArrowRight } from '@posthog/icons'

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
    cn,
} from 'lib/ui/quill'

import { getHogFlowBranchColor, getHogFlowBranchTint, useHogFlowBranchSelection } from '../HogFlowBranchSelection'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowTreeDropzone } from './HogFlowTreeDropzone'
import { HogFlowTreeStep } from './HogFlowTreeStep'
import { countWorkflowTreeNodes } from './workflowTree'
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
    const joinEdge = node.branches.find((branch) => branch.sequence.trailingEdge)?.sequence.trailingEdge
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
                            const branchStepCount = countWorkflowTreeNodes(branch.sequence)

                            return (
                                <div
                                    key={`${branch.edge.from}-${branch.edge.type}-${branch.edge.index ?? 'continue'}`}
                                    className={cn(
                                        'flex min-w-0 flex-col ps-3 transition-[border-width] motion-reduce:transition-none',
                                        isBranchSelected ? 'border-s-4' : 'border-s-2'
                                    )}
                                    style={{ borderColor: branchColor }}
                                    data-workflow-branch-index={branchIndex ?? 'continue'}
                                >
                                    <Item
                                        render={<button type="button" />}
                                        variant="muted"
                                        size="xs"
                                        className={cn('flex-nowrap text-start', isBranchSelected && 'border-2')}
                                        style={{
                                            borderColor: branchColor,
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
                                            className="font-mono"
                                            style={{ color: branchColor, borderColor: branchColor }}
                                        >
                                            {branch.edge.type === 'continue' ? 'ELSE' : 'IF'}
                                        </Badge>
                                        <ItemContent className="min-w-0">
                                            <ItemTitle className="max-w-full truncate">{branch.label}</ItemTitle>
                                        </ItemContent>
                                        <Text size="xs" variant="muted" render={<span />} className="ms-auto shrink-0">
                                            {branchStepCount} {branchStepCount === 1 ? 'step' : 'steps'}
                                        </Text>
                                    </Item>
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
                            />
                        </>
                    )}
                </Collapsible>
            )}
        </div>
    )
}
