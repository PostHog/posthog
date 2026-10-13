import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useCallback, useRef, useState } from 'react'
import type { DragEvent, ReactNode } from 'react'

import { IconCopy, IconDrag, IconTrash, IconTrends, IconX } from '@posthog/icons'

import { EditableField } from 'lib/components/EditableField/EditableField'
import { Badge, Button, Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle, cn } from 'lib/ui/quill'

import { workflowLogic } from '../../workflowLogic'
import { useHogFlowBranchSelection } from '../HogFlowBranchSelection'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { getStepMetricsUrl } from '../panel/stepMetricsUrl'
import { StepView } from '../steps/components/StepView'
import { useHogFlowStep } from '../steps/HogFlowSteps'
import { isScheduleTrigger } from '../steps/types'
import type { HogFlowAction, HogFlowActionNode } from '../types'
import { HogFlowTreeStepSettings } from './HogFlowTreeStepSettings'
import { isBranchingAction } from './workflowTree'

export function HogFlowTreeStep({
    action,
    onDragEnd,
    onDragStart,
    collapseControl,
    stepId,
    canDrag = !['trigger', 'exit'].includes(action.type) && !isBranchingAction(action),
}: {
    action: HogFlowAction
    onDragEnd: () => void
    onDragStart: (event: DragEvent<HTMLDivElement>, actionId: string, dragPreviewElement: HTMLDivElement | null) => void
    collapseControl?: ReactNode
    stepId: string
    canDrag?: boolean
}): JSX.Element {
    const { animatingEdgePair, nodesById, selectedNode } = useValues(hogFlowEditorLogic)
    const { duplicateNodeBelow, onNodesDelete, setSelectedNodeId, setWorkflowAction } = useActions(hogFlowEditorLogic)
    const { setSelectedBranch } = useHogFlowBranchSelection()
    const { actionValidationErrorsById, workflow } = useValues(workflowLogic)
    const step = useHogFlowStep(action)
    const dragPreviewRef = useRef<HTMLDivElement>(null)
    const [closing, setClosing] = useState(false)
    // Deselect only once the settings finish collapsing, because they need the selection to render.
    const finishClosing = useCallback(() => {
        setClosing(false)
        setSelectedNodeId(null)
    }, [setSelectedNodeId])

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
    const previews = step?.previews ?? []
    const canEditDescription = !isScheduleTrigger(action)
    const hasFooterContent = !!action.description || previews.length > 0 || (isSelected && canEditDescription)
    const stepMetricsUrl = isSelected ? getStepMetricsUrl(workflow, action.id) : null

    return (
        <div className={cn('rounded-md', isSelected && 'ring-2 ring-ring/30')}>
            <Item
                variant="outline"
                size="xs"
                className={cn(
                    'relative flex-nowrap !gap-2 bg-card !px-2 !py-1.5',
                    isSelected && 'rounded-b-none border-ring border-b-transparent',
                    isAnimationTarget && 'border-success',
                    'data-[workflow-tree-dragging]:opacity-50'
                )}
                data-attr="workflow-tree-step"
                id={stepId}
            >
                <Button
                    type="button"
                    variant="link"
                    className="absolute inset-0 z-0 h-full w-full"
                    aria-label={isSelected ? `Close ${action.name}` : `Edit ${action.name}`}
                    aria-expanded={isSelected && !closing}
                    onClick={() => {
                        if (isSelected) {
                            setClosing(true)
                            return
                        }
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
                        <ItemTitle className="pointer-events-none min-w-0 flex-1 max-w-full break-words whitespace-normal leading-tight">
                            {isSelected ? (
                                <EditableField
                                    name="step-name"
                                    value={action.name}
                                    onSave={(value) => {
                                        const trimmed = value.trim()
                                        if (trimmed) {
                                            setWorkflowAction(action.id, { ...action, name: trimmed })
                                        }
                                    }}
                                    placeholder="Step name"
                                    minLength={1}
                                    saveOnBlur
                                    clickToEdit
                                    compactButtons
                                    compactIcon
                                    className="pointer-events-auto"
                                    data-attr="workflow-step-name"
                                />
                            ) : (
                                action.name
                            )}
                        </ItemTitle>
                        {(canHaveActions || isSelected) && (
                            <ItemActions
                                className={cn(
                                    'pointer-events-auto',
                                    '!gap-px ms-auto shrink-0 transition-opacity group-hover/item:opacity-100 group-focus-within/item:opacity-100',
                                    isSelected ? 'opacity-100' : 'opacity-20'
                                )}
                            >
                                {stepMetricsUrl && (
                                    <Button
                                        type="button"
                                        variant="default"
                                        size="icon-sm"
                                        aria-label="View metrics for this step"
                                        title="View metrics for this step"
                                        onClick={() => router.actions.push(stepMetricsUrl)}
                                        data-attr="workflow-step-metrics-link"
                                    >
                                        <IconTrends />
                                    </Button>
                                )}
                                {canHaveActions && canDuplicate && (
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
                                {canHaveActions && (
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
                                )}
                                {isSelected && (
                                    <Button
                                        type="button"
                                        variant="default"
                                        size="icon-sm"
                                        aria-label="Close step"
                                        title="Close step"
                                        onClick={() => setClosing(true)}
                                        data-attr="workflow-step-close"
                                    >
                                        <IconX />
                                    </Button>
                                )}
                            </ItemActions>
                        )}
                    </div>
                    {hasFooterContent && (
                        <div className="flex min-w-0 flex-wrap items-center gap-2">
                            {isSelected && canEditDescription ? (
                                <ItemDescription className="pointer-events-none min-w-0 flex-1 whitespace-normal break-words leading-tight">
                                    <EditableField
                                        name="step-description"
                                        value={action.description || ''}
                                        onSave={(value) =>
                                            setWorkflowAction(action.id, { ...action, description: value.trim() })
                                        }
                                        placeholder="Add a description (optional)"
                                        multiline
                                        saveOnBlur
                                        clickToEdit
                                        compactButtons
                                        compactIcon
                                        className="pointer-events-auto"
                                        data-attr="workflow-step-description"
                                    />
                                </ItemDescription>
                            ) : (
                                action.description && (
                                    <ItemDescription className="pointer-events-none min-w-0 flex-1 whitespace-normal break-words leading-tight">
                                        {action.description}
                                    </ItemDescription>
                                )
                            )}
                            {previews.length > 0 && (
                                <div className="pointer-events-none ms-auto flex min-w-0 max-w-full flex-wrap items-center justify-end gap-1">
                                    {previews.slice(0, 3).map((preview, index) => (
                                        <Badge
                                            key={`${preview.label}-${index}`}
                                            variant="default"
                                            className="max-w-full whitespace-normal break-words h-auto min-h-4 py-0 leading-tight"
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
                        className="pointer-events-none absolute -end-1 -top-1 z-20 !size-5 !min-w-5 shrink-0 !rounded-full border-2 border-card !p-0 !leading-none shadow-sm"
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
            {isSelected && (
                <div className="overflow-hidden rounded-b-md border border-t-0 border-ring">
                    <HogFlowTreeStepSettings open={!closing} onClosed={finishClosing} />
                </div>
            )}
        </div>
    )
}
