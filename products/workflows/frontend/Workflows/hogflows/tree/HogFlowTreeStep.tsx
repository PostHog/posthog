import { useActions, useValues } from 'kea'
import type { DragEvent } from 'react'

import { IconCopy, IconDrag, IconTrash } from '@posthog/icons'

import { Badge, Button, Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle, cn } from 'lib/ui/quill'

import { workflowLogic } from '../../workflowLogic'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { useHogFlowStep } from '../steps/HogFlowSteps'
import type { HogFlowAction } from '../types'
import { isBranchingAction } from './workflowTree'

function stepMediaClassName(action: HogFlowAction): string {
    if (action.type === 'trigger') {
        return 'bg-fill-success-highlight text-success'
    }
    if (action.type === 'exit') {
        return 'bg-muted text-muted-foreground'
    }
    if (isBranchingAction(action)) {
        return 'bg-fill-warning-highlight text-warning'
    }
    return 'bg-fill-info-tertiary text-primary'
}

export function HogFlowTreeStep({
    action,
    branchCount,
    dragged,
    onDragEnd,
    onDragStart,
    showCollapseOffset = false,
}: {
    action: HogFlowAction
    branchCount?: number
    dragged: boolean
    onDragEnd: () => void
    onDragStart: (event: DragEvent<HTMLDivElement>, actionId: string) => void
    showCollapseOffset?: boolean
}): JSX.Element {
    const { animatingEdgePair, nodesById, selectedNode, selectedNodeCanBeCopiedOrMoved, selectedNodeCanBeDeleted } =
        useValues(hogFlowEditorLogic)
    const { duplicateNodeBelow, onNodesDelete, setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const step = useHogFlowStep(action)

    const isSelected = selectedNode?.id === action.id
    const node = nodesById[action.id] ?? (isSelected ? selectedNode : null)
    const canDrag = !['trigger', 'exit'].includes(action.type) && !isBranchingAction(action)
    const validationResult = actionValidationErrorsById[action.id]
    const hasValidationIssue =
        validationResult?.valid === false || Object.keys(validationResult?.warnings ?? {}).length > 0
    const isAnimationTarget = animatingEdgePair?.endsWith(`->${action.id}`) ?? false

    return (
        <Item
            variant="outline"
            size="sm"
            className={cn(
                'relative flex-nowrap bg-card',
                showCollapseOffset && 'ps-10',
                isSelected && 'border-ring ring-2 ring-ring/30',
                isAnimationTarget && 'border-success',
                dragged && 'opacity-50'
            )}
            data-attr="workflow-tree-step"
        >
            <Button
                type="button"
                variant="link"
                className="absolute inset-0 z-0 h-full w-full"
                aria-label={`Edit ${action.name}`}
                aria-pressed={isSelected}
                onClick={() => setSelectedNodeId(action.id)}
            />
            {canDrag && (
                <div
                    draggable
                    className="relative z-10 flex cursor-grab items-center text-muted-foreground active:cursor-grabbing"
                    onDragStart={(event) => onDragStart(event, action.id)}
                    onDragEnd={onDragEnd}
                    data-attr="workflow-tree-step-drag"
                >
                    <IconDrag />
                </div>
            )}
            <ItemMedia variant="image" className={cn('relative z-10', stepMediaClassName(action))}>
                {step?.icon}
            </ItemMedia>
            <ItemContent className="pointer-events-none relative z-10 min-w-0">
                <ItemTitle className="max-w-full truncate">{action.name}</ItemTitle>
                {action.description && <ItemDescription className="truncate">{action.description}</ItemDescription>}
                {!!step?.previews.length && (
                    <div className="flex max-w-full flex-wrap gap-1">
                        {step.previews.slice(0, 3).map((preview, index) => (
                            <Badge key={`${preview.label}-${index}`} variant="default" className="max-w-48 truncate">
                                {preview.icon}
                                {preview.label}
                            </Badge>
                        ))}
                    </div>
                )}
            </ItemContent>
            {branchCount !== undefined && (
                <Badge variant="default" className="relative z-10 ms-auto shrink-0">
                    {branchCount} branches
                </Badge>
            )}
            {hasValidationIssue && (
                <Badge variant="warning" className="relative z-10 shrink-0" aria-label="Some fields need attention">
                    !
                </Badge>
            )}
            <ItemActions
                className={cn(
                    'relative z-10 shrink-0 transition-opacity',
                    branchCount === undefined && !hasValidationIssue && 'ms-auto',
                    isSelected
                        ? 'opacity-100'
                        : 'pointer-events-none opacity-0 group-hover/item:pointer-events-auto group-hover/item:opacity-100 group-focus-within/item:pointer-events-auto group-focus-within/item:opacity-100'
                )}
            >
                {isSelected && selectedNodeCanBeCopiedOrMoved && (
                    <Button
                        type="button"
                        variant="default"
                        size="icon-sm"
                        aria-label="Duplicate step"
                        title="Duplicate step"
                        onClick={() => duplicateNodeBelow(action.id)}
                        data-attr="workflow-tree-duplicate-step"
                    >
                        <IconCopy />
                    </Button>
                )}
                {isSelected && node?.deletable && (
                    <Button
                        type="button"
                        variant="default"
                        size="icon-sm"
                        aria-label="Delete step"
                        title={selectedNodeCanBeDeleted ? 'Delete step' : 'Clean up branching steps first'}
                        disabled={!selectedNodeCanBeDeleted}
                        onClick={() => {
                            onNodesDelete([node])
                            setSelectedNodeId(null)
                        }}
                        data-attr="workflow-tree-delete-step"
                    >
                        <IconTrash />
                    </Button>
                )}
            </ItemActions>
        </Item>
    )
}
