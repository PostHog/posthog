import { useActions, useValues } from 'kea'
import { useState } from 'react'
import type { DragEvent } from 'react'

import { IconPlus } from '@posthog/icons'

import { Button, cn, Popover, PopoverContent, PopoverTrigger } from 'lib/ui/quill'

import { type CreateActionType, hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowEditorPanelBuild } from '../panel/HogFlowEditorPanelBuild'
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
}): JSX.Element {
    const { workflow } = useValues(hogFlowEditorLogic)
    const {
        moveNodeToEdge,
        onDragOver,
        onDrop,
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
    const handleInsertAction = (action: CreateActionType): void => {
        setPickerOpen(false)
        setNodeToBeAdded(action)

        if (isBranchJoin && !joinEdges) {
            setHighlightedDropzoneNodeId(`dropzone_target_${edge.to}_branch_join`)
            onDrop()
        } else {
            onDrop(undefined, edge, joinEdges)
        }
    }
    return (
        <div className={cn('group relative flex w-full items-center justify-center', compact ? 'h-2' : 'h-4')}>
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
                        (pickerOpen || !showConnector) && 'opacity-100',
                        showConnector && 'group-hover:opacity-100'
                    )}
                />
                <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
                    <PopoverTrigger
                        render={
                            <Button
                                type="button"
                                variant="outline"
                                size="icon-sm"
                                className={cn(
                                    'absolute -right-2 top-1/2 z-10 !size-4 -translate-y-1/2 border-0 bg-transparent p-0 hover:bg-transparent focus-visible:outline-none'
                                )}
                                aria-label="Insert step here"
                                data-attr="workflow-tree-insert-action"
                            />
                        }
                    >
                        <span
                            className={cn(
                                'flex size-4 items-center justify-center rounded-full border border-primary bg-primary text-primary-foreground opacity-0 transition-[opacity,box-shadow] group-hover:opacity-100 group-hover:shadow-sm',
                                pickerOpen && 'opacity-100 shadow-sm'
                            )}
                        >
                            <IconPlus className="size-3" />
                        </span>
                    </PopoverTrigger>
                    <PopoverContent side="bottom" align="end" className="w-72 max-h-96 overflow-hidden p-0">
                        <HogFlowEditorPanelBuild className="max-h-96 p-2" onActionSelect={handleInsertAction} />
                    </PopoverContent>
                </Popover>
            </div>
            <div
                className={cn(
                    'absolute -inset-y-3 inset-x-0 z-20 items-center',
                    isAdjacentToDraggedAction
                        ? 'hidden'
                        : active
                          ? 'flex'
                          : 'hidden group-data-[workflow-tree-dragging=true]/tree:flex'
                )}
                onDragOver={handleDragOver}
                onDragLeave={() => setHighlighted(false)}
                onDrop={handleDrop}
                data-attr="workflow-tree-dropzone"
            >
                <div
                    aria-hidden="true"
                    className={cn(
                        'absolute inset-x-0 top-1/2 h-0.5 -translate-y-1/2 bg-primary opacity-30 transition-opacity duration-150',
                        highlighted ? 'opacity-100' : 'group-hover:opacity-100'
                    )}
                />
                <span
                    aria-hidden="true"
                    className={cn(
                        'absolute -right-2 top-1/2 flex size-4 -translate-y-1/2 items-center justify-center rounded-full border border-primary bg-primary text-primary-foreground opacity-30 transition-[opacity,transform,box-shadow] duration-150',
                        highlighted
                            ? 'scale-110 opacity-100 shadow-sm'
                            : 'group-hover:scale-110 group-hover:opacity-100 group-hover:shadow-sm'
                    )}
                >
                    <IconPlus className="size-3" />
                </span>
            </div>
        </div>
    )
}
