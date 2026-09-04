import { useState } from 'react'
import type { CSSProperties, DragEvent } from 'react'

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

import { HogFlowTreeDropzone } from './HogFlowTreeDropzone'
import { HogFlowTreeStep } from './HogFlowTreeStep'
import { countWorkflowTreeNodes } from './workflowTree'
import type { WorkflowTreeNode } from './workflowTree'

const BRANCH_LIMIT = 6
const BRANCH_COLORS = [
    'var(--data-color-1)',
    'var(--data-color-7)',
    'var(--data-color-14)',
    'var(--data-color-12)',
    'var(--data-color-11)',
    'var(--data-color-4)',
]

export function HogFlowTreeNode({
    activeDropzones,
    draggedActionId,
    node,
    onDragEnd,
    onDragStart,
}: {
    activeDropzones: boolean
    draggedActionId: string | null
    node: WorkflowTreeNode
    onDragEnd: () => void
    onDragStart: (event: DragEvent<HTMLDivElement>, actionId: string) => void
}): JSX.Element {
    const [showAllBranches, setShowAllBranches] = useState(false)
    const visibleBranches = showAllBranches ? node.branches : node.branches.slice(0, BRANCH_LIMIT)
    const hiddenBranchCount = node.branches.length - visibleBranches.length
    const joinEdge = node.branches.find((branch) => branch.sequence.trailingEdge)?.sequence.trailingEdge

    const step = (
        <HogFlowTreeStep
            action={node.action}
            dragged={draggedActionId === node.action.id}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            showCollapseOffset={node.branches.length > 0}
        />
    )

    return (
        <div className="flex w-full flex-col">
            {node.incomingEdge && (
                <HogFlowTreeDropzone
                    active={activeDropzones}
                    draggedActionId={draggedActionId}
                    edge={node.incomingEdge}
                />
            )}
            {node.branches.length === 0 ? (
                step
            ) : (
                <Collapsible variant="folder" defaultOpen>
                    <CollapsibleHeader>
                        <CollapsibleTrigger iconOnly className="ms-2 z-20">
                            Expand or collapse branches
                        </CollapsibleTrigger>
                        {step}
                    </CollapsibleHeader>
                    <CollapsibleContent className="flex flex-col gap-3 pt-2">
                        {visibleBranches.map((branch, index) => {
                            const branchColor =
                                branch.edge.type === 'continue'
                                    ? 'var(--muted-foreground)'
                                    : BRANCH_COLORS[index % BRANCH_COLORS.length]
                            const branchStyle = { borderColor: branchColor } satisfies CSSProperties
                            const branchStepCount = countWorkflowTreeNodes(branch.sequence)

                            return (
                                <div
                                    key={`${branch.edge.from}-${branch.edge.type}-${branch.edge.index ?? 'continue'}`}
                                    className="flex min-w-0 flex-col border-s-2 ps-3"
                                    style={branchStyle}
                                >
                                    <Item variant="muted" size="xs" className="flex-nowrap" style={branchStyle}>
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
                                    {branch.sequence.nodes.map((childNode) => (
                                        <HogFlowTreeNode
                                            key={childNode.action.id}
                                            node={childNode}
                                            activeDropzones={activeDropzones}
                                            draggedActionId={draggedActionId}
                                            onDragStart={onDragStart}
                                            onDragEnd={onDragEnd}
                                        />
                                    ))}
                                    {branch.sequence.trailingEdge && (
                                        <HogFlowTreeDropzone
                                            active={activeDropzones}
                                            draggedActionId={draggedActionId}
                                            edge={branch.sequence.trailingEdge}
                                        />
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
                        {node.joinActionId && (
                            <>
                                <div className="flex items-center gap-2">
                                    <Separator className="flex-1" />
                                    <Text size="xs" variant="muted" render={<span />}>
                                        Branches continue below
                                    </Text>
                                    <Separator className="flex-1" />
                                </div>
                                {joinEdge && (
                                    <HogFlowTreeDropzone
                                        active={activeDropzones}
                                        draggedActionId={draggedActionId}
                                        edge={joinEdge}
                                        isBranchJoin
                                    />
                                )}
                            </>
                        )}
                    </CollapsibleContent>
                </Collapsible>
            )}
        </div>
    )
}
