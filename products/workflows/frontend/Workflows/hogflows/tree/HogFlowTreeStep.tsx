import { useActions, useValues } from 'kea'
import { useRef } from 'react'
import type { DragEvent, ReactNode } from 'react'

import { IconCopy, IconDrag, IconTrash } from '@posthog/icons'

import { Badge, Button, Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle, cn } from 'lib/ui/quill'

import { workflowLogic } from '../../workflowLogic'
import { useHogFlowBranchSelection } from '../HogFlowBranchSelection'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { StepView } from '../steps/components/StepView'
import { useHogFlowStep } from '../steps/HogFlowSteps'
import type { HogFlowAction, HogFlowActionNode } from '../types'
import { HogFlowTreeBranchIndicator } from './HogFlowTreeBranchIndicator'
import { isBranchingAction } from './workflowTree'

export function HogFlowTreeStep({
    action,
    onDragEnd,
    onDragStart,
    branchColor,
    collapseControl,
    canDrag = !['trigger', 'exit'].includes(action.type) && !isBranchingAction(action),
}: {
    action: HogFlowAction
    onDragEnd: () => void
    onDragStart: (event: DragEvent<HTMLDivElement>, actionId: string, dragPreviewElement: HTMLDivElement | null) => void
    branchColor?: string
    collapseControl?: ReactNode
    canDrag?: boolean
}): JSX.Element {
    const { animatingEdgePair, nodesById, selectedNode } = useValues(hogFlowEditorLogic)
    const { duplicateNodeBelow, onNodesDelete, setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const { setSelectedBranch } = useHogFlowBranchSelection()
    const { actionValidationErrorsById, workflow } = useValues(workflowLogic)
    const step = useHogFlowStep(action)
    const dragPreviewRef = useRef<HTMLDivElement>(null)

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
    const validationResult = actionValidationErrorsById[action.id]
    const hasValidationIssue =
        validationResult?.valid === false || Object.keys(validationResult?.warnings ?? {}).length > 0
    const isAnimationTarget = animatingEdgePair?.endsWith(`->${action.id}`) ?? false
    const hasFooterContent = !!action.description || !!step?.previews.length

    return (
        <Item
            variant="outline"
            size="xs"
            className={cn(
                'relative flex-nowrap !gap-2 bg-card !px-2 !py-1.5',
                isSelected && 'border-ring ring-2 ring-ring/30',
                isAnimationTarget && 'border-success',
                'data-[workflow-tree-dragging]:opacity-50'
            )}
            data-attr="workflow-tree-step"
            id={`workflow-tree-step-${action.id}`}
        >
            {branchColor && <HogFlowTreeBranchIndicator color={branchColor} className="inset-y-1" />}
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
                    className="relative z-10 -ms-0.5 -me-1 flex size-5 shrink-0 cursor-grab items-center justify-center text-muted-foreground active:cursor-grabbing"
                    onDragStart={(event) => onDragStart(event, action.id, dragPreviewRef.current)}
                    onDragEnd={onDragEnd}
                    data-attr="workflow-tree-step-drag"
                >
                    <IconDrag className="size-4" />
                </div>
            )}
            <ItemMedia
                variant="image"
                className="pointer-events-none relative z-10 !size-8 shrink-0 [&>img]:!size-6 [&>img]:!object-contain [&>svg]:!size-6 [&>svg]:shrink-0"
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
            <ItemContent className="pointer-events-none relative z-10 min-w-0 gap-0.5">
                <div className="flex min-w-0 items-center gap-1">
                    <ItemTitle className="pointer-events-none min-w-0 flex-1 max-w-full truncate leading-tight">
                        {action.name}
                    </ItemTitle>
                    {canHaveActions && (
                        <ItemActions
                            className={cn(
                                'pointer-events-auto',
                                '!gap-px ms-auto shrink-0 transition-opacity group-hover/item:opacity-100 group-focus-within/item:opacity-100',
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
                </div>
                {hasFooterContent && (
                    <div className="flex min-w-0 items-center gap-2">
                        {action.description && (
                            <ItemDescription className="pointer-events-none min-w-0 flex-1 truncate leading-tight">
                                {action.description}
                            </ItemDescription>
                        )}
                        {!!step?.previews.length && (
                            <div className="pointer-events-none ms-auto flex min-w-0 shrink-0 items-center gap-1 overflow-hidden">
                                {step.previews.slice(0, 3).map((preview, index) => (
                                    <Badge
                                        key={`${preview.label}-${index}`}
                                        variant="default"
                                        className="max-w-36 truncate"
                                    >
                                        {preview.icon}
                                        {preview.label}
                                    </Badge>
                                ))}
                            </div>
                        )}
                    </div>
                )}
            </ItemContent>
            {collapseControl && (
                <div className="pointer-events-auto relative z-10 -my-1.5 -me-2 flex w-10 shrink-0 items-center justify-center border-s">
                    {collapseControl}
                </div>
            )}
            {hasValidationIssue && (
                <Badge
                    variant="warning"
                    className="pointer-events-none absolute end-1 top-1 z-20 shrink-0"
                    aria-label="Some fields need attention"
                >
                    !
                </Badge>
            )}
            <div ref={dragPreviewRef} className="pointer-events-none absolute invisible" aria-hidden="true">
                <div className="origin-top-left scale-150">
                    <StepView action={{ ...action, id: `drag-preview-${action.id}` }} />
                </div>
            </div>
        </Item>
    )
}
