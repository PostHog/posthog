import { useActions, useValues } from 'kea'
import type { DragEvent } from 'react'

import { IconCopy, IconDrag, IconTrash } from '@posthog/icons'

import { Badge, Button, Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle, cn } from 'lib/ui/quill'

import { workflowLogic } from '../../workflowLogic'
import { useHogFlowBranchSelection } from '../HogFlowBranchSelection'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { useHogFlowStep } from '../steps/HogFlowSteps'
import type { HogFlowAction, HogFlowActionNode } from '../types'
import { isBranchingAction } from './workflowTree'

export function HogFlowTreeStep({
    action,
    dragged,
    onDragEnd,
    onDragStart,
    showCollapseOffset = false,
}: {
    action: HogFlowAction
    dragged: boolean
    onDragEnd: () => void
    onDragStart: (event: DragEvent<HTMLDivElement>, actionId: string) => void
    showCollapseOffset?: boolean
}): JSX.Element {
    const { animatingEdgePair, nodesById, selectedNode } = useValues(hogFlowEditorLogic)
    const { duplicateNodeBelow, onNodesDelete, setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const { setSelectedBranch } = useHogFlowBranchSelection()
    const { actionValidationErrorsById, workflow } = useValues(workflowLogic)
    const step = useHogFlowStep(action)

    const isSelected = selectedNode?.id === action.id
    const canHaveActions = !['trigger', 'exit'].includes(action.type)
    const outgoingActionIds = workflow.edges.filter((edge) => edge.from === action.id).map((edge) => edge.to)
    const canDelete = canHaveActions && (outgoingActionIds.length === 1 || new Set(outgoingActionIds).size === 1)
    const canDuplicate = canDelete && !isBranchingAction(action)
    const node =
        nodesById[action.id] ??
        ({
            id: action.id,
            type: 'action',
            data: action,
            position: { x: 0, y: 0 },
            deletable: canHaveActions,
            selectable: true,
            draggable: false,
            connectable: false,
        } satisfies HogFlowActionNode)
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
                onClick={() => {
                    setSelectedBranch(null)
                    setSelectedNodeId(action.id)
                }}
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
            <ItemMedia
                variant="image"
                className="relative z-10 !size-9 shrink-0 [&>img]:!size-5 [&>img]:!object-contain [&>svg]:!size-5 [&>svg]:shrink-0"
                style={
                    step?.color
                        ? {
                              alignSelf: 'center',
                              translate: 'none',
                              backgroundColor: `${step.color}20`,
                              color: step.color,
                          }
                        : { alignSelf: 'center', translate: 'none' }
                }
            >
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
            {hasValidationIssue && (
                <Badge
                    variant="warning"
                    className="pointer-events-none absolute end-1 top-1 z-20 shrink-0"
                    aria-label="Some fields need attention"
                >
                    !
                </Badge>
            )}
            {canHaveActions && (
                <ItemActions
                    className={cn(
                        'relative z-10 ms-auto me-4 shrink-0 transition-opacity group-hover/item:opacity-100 group-focus-within/item:opacity-100',
                        isSelected ? 'opacity-100' : 'opacity-20'
                    )}
                >
                    {canDuplicate && (
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
                    <Button
                        type="button"
                        variant="default"
                        size="icon-sm"
                        aria-label="Delete step"
                        title={canDelete ? 'Delete step' : 'Clean up branching steps first'}
                        disabled={!canDelete}
                        onClick={() => {
                            onNodesDelete([node])
                            setSelectedNodeId(null)
                        }}
                        data-attr="workflow-tree-delete-step"
                    >
                        <IconTrash />
                    </Button>
                </ItemActions>
            )}
        </Item>
    )
}
