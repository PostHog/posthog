import { useActions, useValues } from 'kea'
import { useState } from 'react'
import type { DragEvent } from 'react'

import { IconPlus } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton, type LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn, Popover, PopoverContent, PopoverTrigger } from 'lib/ui/quill'

import { type CreateActionType, hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowEditorPanelBuild } from '../panel/HogFlowEditorPanelBuild'
import { StepPickerModal } from '../stepPicker/StepPickerModal'
import type { HogFlowEdge } from '../types'
import { computeMoveTreeBranchEdges, isBranchingAction } from './workflowTree'

export function HogFlowTreeDropzone({
    active,
    draggedActionId,
    draggedActionIdRef,
    onDragEnd,
    edge,
    isBranchJoin = false,
    joinEdges,
    showConnector = true,
    compact = false,
    insertionLabel,
    alwaysVisible = false,
}: {
    active: boolean
    draggedActionId: string | null
    draggedActionIdRef: { current: string | null }
    onDragEnd: () => void
    edge: HogFlowEdge
    isBranchJoin?: boolean
    joinEdges?: HogFlowEdge[]
    showConnector?: boolean
    compact?: boolean
    insertionLabel?: string
    alwaysVisible?: boolean
}): JSX.Element {
    const { workflow, isPlacingNewStep } = useValues(hogFlowEditorLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const opensStepPicker = !!featureFlags[FEATURE_FLAGS.WORKFLOWS_STEP_PICKER]
    const {
        moveNodeToEdge,
        onDragOver,
        onDrop,
        placeNewStep,
        setHighlightedDropzoneNodeId,
        setNodeToBeAdded,
        setSelectedNodeId,
        setWorkflowInfo,
    } = useActions(hogFlowEditorLogic)
    const [highlighted, setHighlighted] = useState(false)
    const [pickerOpen, setPickerOpen] = useState(false)
    const isAdjacentToDraggedAction = draggedActionId === edge.to || (!isBranchJoin && draggedActionId === edge.from)
    const handleDragOver = (event: DragEvent<HTMLElement>): void => {
        setHighlighted(true)
        onDragOver(event)
    }
    const handleDrop = (event: DragEvent<HTMLElement>): void => {
        setHighlighted(false)
        const draggedActionId = draggedActionIdRef.current
        if (draggedActionId) {
            if (edge.to === draggedActionId || (!isBranchJoin && edge.from === draggedActionId)) {
                onDragEnd()
                return
            }
            const action = workflow.actions.find((action) => action.id === draggedActionId)
            if (!action || !isBranchingAction(action)) {
                moveNodeToEdge(draggedActionId, edge, isBranchJoin, joinEdges)
            } else {
                const newEdges = computeMoveTreeBranchEdges(workflow, draggedActionId, edge, isBranchJoin, joinEdges)
                if (newEdges) {
                    setWorkflowInfo({ actions: workflow.actions, edges: newEdges })
                    setSelectedNodeId(draggedActionId)
                }
            }
            onDragEnd()
        } else if (isBranchJoin) {
            if (joinEdges) {
                onDrop(event, edge, joinEdges)
            } else {
                setHighlightedDropzoneNodeId(`dropzone_target_${edge.to}_branch_join`)
                onDrop(event)
            }
        } else {
            onDrop(event, edge)
        }
    }
    const insertHere = (insert: (targetEdge?: HogFlowEdge, joinEdges?: HogFlowEdge[]) => void): void => {
        if (isBranchJoin && !joinEdges) {
            setHighlightedDropzoneNodeId(`dropzone_target_${edge.to}_branch_join`)
            insert()
        } else {
            insert(edge, joinEdges)
        }
    }
    const handleInsertAction = (action: CreateActionType): void => {
        setPickerOpen(false)
        setNodeToBeAdded(action)
        insertHere((targetEdge, joinEdges) => onDrop(undefined, targetEdge, joinEdges))
    }
    const insertButtonProps: LemonButtonProps = {
        htmlType: 'button',
        type: 'tertiary',
        size: 'xsmall',
        tooltip: insertionLabel ?? 'Insert step here',
        className: alwaysVisible
            ? 'relative z-10 me-auto min-w-0 max-w-full bg-transparent text-muted-foreground'
            : 'absolute -right-2 top-1/2 z-10 !size-4 -translate-y-1/2 border-0 !bg-transparent !p-0',
        'aria-label': insertionLabel ?? 'Insert step here',
        'data-attr': 'workflow-tree-insert-action',
    }
    const insertButtonContent = alwaysVisible ? (
        <>
            <IconPlus className="size-3 shrink-0" />
            <span className="truncate">{insertionLabel}</span>
        </>
    ) : (
        <span
            className={cn(
                'flex size-4 items-center justify-center rounded-full border border-primary bg-primary text-primary-foreground opacity-0 transition-[opacity,box-shadow] group-hover:opacity-100 group-focus-within:opacity-100 group-hover:shadow-sm',
                pickerOpen && 'opacity-100 shadow-sm'
            )}
        >
            <IconPlus className="size-3" />
        </span>
    )
    return (
        <div
            className={cn(
                'group relative flex w-full items-center justify-center',
                alwaysVisible ? 'min-h-8' : compact ? 'h-2' : 'h-4'
            )}
            data-workflow-tree-dropzone-candidate
            data-workflow-tree-dropzone-disabled={isAdjacentToDraggedAction || undefined}
        >
            <div
                className={cn(
                    'absolute inset-0 flex items-center justify-center',
                    active ? 'hidden' : 'group-data-[workflow-tree-dragging=true]/tree:hidden'
                )}
            >
                <div
                    aria-hidden="true"
                    className={cn(
                        'absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-muted-foreground/50 opacity-0 transition-opacity',
                        pickerOpen && 'opacity-100',
                        (showConnector || insertionLabel) && 'group-hover:opacity-100 group-focus-within:opacity-100'
                    )}
                />
                {opensStepPicker ? (
                    <>
                        <LemonButton {...insertButtonProps} onClick={() => setPickerOpen(true)}>
                            {insertButtonContent}
                        </LemonButton>
                        {pickerOpen && (
                            <StepPickerModal
                                isOpen
                                onClose={() => setPickerOpen(false)}
                                surface="tree"
                                onPick={handleInsertAction}
                            />
                        )}
                    </>
                ) : (
                    <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
                        <PopoverTrigger render={<LemonButton {...insertButtonProps} />}>
                            {insertButtonContent}
                        </PopoverTrigger>
                        <PopoverContent side="bottom" align="end" className="w-72 max-h-96 overflow-hidden p-0">
                            <HogFlowEditorPanelBuild className="max-h-96 p-2" onActionSelect={handleInsertAction} />
                        </PopoverContent>
                    </Popover>
                )}
            </div>
            {isPlacingNewStep && (
                <button
                    type="button"
                    aria-label={insertionLabel ?? 'Add step here'}
                    className="group/placement absolute -inset-y-2 inset-x-0 z-20 flex cursor-pointer items-center"
                    onClick={() => insertHere(placeNewStep)}
                >
                    <span
                        aria-hidden="true"
                        className="absolute inset-x-0 top-1/2 h-0.5 -translate-y-1/2 bg-primary opacity-40 transition-opacity group-hover/placement:opacity-100 group-focus-visible/placement:opacity-100"
                    />
                    <span
                        aria-hidden="true"
                        className="absolute -right-2 top-1/2 flex size-4 -translate-y-1/2 items-center justify-center rounded-full border border-primary bg-primary text-primary-foreground opacity-70 transition-[opacity,transform] group-hover/placement:scale-110 group-hover/placement:opacity-100 group-focus-visible/placement:opacity-100"
                    >
                        <IconPlus className="size-3" />
                    </span>
                </button>
            )}
            <div
                className={cn(
                    'absolute -inset-y-3 inset-x-0 z-20 items-center',
                    isAdjacentToDraggedAction
                        ? 'hidden'
                        : 'hidden group-data-[workflow-tree-dropzone-closest=true]:flex'
                )}
                onDragOver={handleDragOver}
                onDragLeave={() => setHighlighted(false)}
                onDrop={handleDrop}
                data-attr="workflow-tree-dropzone"
            >
                <div
                    aria-hidden="true"
                    className={cn(
                        'absolute inset-x-0 top-1/2 h-0.5 -translate-y-1/2 bg-primary opacity-30 transition-opacity duration-150 group-data-[workflow-tree-dropzone-closest=true]:opacity-100',
                        highlighted && 'opacity-100'
                    )}
                />
                <span
                    aria-hidden="true"
                    className={cn(
                        'absolute -right-2 top-1/2 flex size-4 -translate-y-1/2 items-center justify-center rounded-full border border-primary bg-primary text-primary-foreground opacity-30 transition-[opacity,transform,box-shadow] duration-150 group-data-[workflow-tree-dropzone-closest=true]:scale-110 group-data-[workflow-tree-dropzone-closest=true]:opacity-100 group-data-[workflow-tree-dropzone-closest=true]:shadow-sm',
                        highlighted && 'scale-110 opacity-100 shadow-sm'
                    )}
                >
                    <IconPlus className="size-3" />
                </span>
            </div>
        </div>
    )
}
