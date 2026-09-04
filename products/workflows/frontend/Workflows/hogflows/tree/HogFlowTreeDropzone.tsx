import { useActions, useValues } from 'kea'
import { useState } from 'react'
import type { DragEvent, MouseEvent } from 'react'

import { IconPlus } from '@posthog/icons'

import { Button, cn, Popover, PopoverContent, PopoverTrigger } from 'lib/ui/quill'

import { type CreateActionType, hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowEditorPanelBuild } from '../panel/HogFlowEditorPanelBuild'
import type { HogFlowEdge } from '../types'
import { computeMoveTreeBranchEdges, isBranchingAction } from './workflowTree'

export function HogFlowTreeDropzone({
    active,
    draggedActionIdRef,
    onDragEnd,
    edge,
    isBranchJoin = false,
    joinEdges,
    showConnector = true,
    compact = false,
}: {
    active: boolean
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
    const [insertSide, setInsertSide] = useState<'left' | 'right'>('right')
    const [pickerOpen, setPickerOpen] = useState(false)
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
    const handleGapMouseMove = (event: MouseEvent<HTMLDivElement>): void => {
        const { left, width } = event.currentTarget.getBoundingClientRect()
        const nextInsertSide = event.clientX - left < width / 2 ? 'left' : 'right'
        setInsertSide((currentInsertSide) =>
            currentInsertSide === nextInsertSide ? currentInsertSide : nextInsertSide
        )
    }

    return (
        <div
            className={cn('group relative flex w-full items-center justify-center', compact ? 'h-2' : 'h-7')}
            onMouseMove={handleGapMouseMove}
        >
            <div
                className={cn(
                    'absolute inset-0 flex items-center justify-center',
                    active ? 'hidden' : 'group-data-[workflow-tree-dragging=true]/tree:hidden'
                )}
            >
                {showConnector && (
                    <svg
                        className="h-full w-4 text-muted-foreground opacity-60"
                        viewBox="0 0 16 28"
                        fill="none"
                        aria-hidden="true"
                    >
                        <path d="M8 0v20m-5-2 5 5 5-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                    </svg>
                )}
                <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
                    <PopoverTrigger
                        render={
                            <Button
                                type="button"
                                variant="outline"
                                size="icon-sm"
                                className={cn(
                                    'absolute top-1/2 z-10 -translate-y-1/2 rounded-full border-primary bg-background text-primary shadow-sm opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100',
                                    pickerOpen && 'opacity-100',
                                    insertSide === 'left' ? 'left-2' : 'right-2'
                                )}
                                aria-label="Insert step here"
                                data-attr="workflow-tree-insert-action"
                            />
                        }
                    >
                        <IconPlus />
                    </PopoverTrigger>
                    <PopoverContent
                        side="bottom"
                        align={insertSide === 'left' ? 'start' : 'end'}
                        className="w-72 max-h-96 overflow-hidden p-0"
                    >
                        <HogFlowEditorPanelBuild className="max-h-96 p-2" onActionSelect={handleInsertAction} />
                    </PopoverContent>
                </Popover>
            </div>
            <div
                className={cn(
                    compact ? 'absolute -inset-y-3 inset-x-0 items-center' : 'relative h-full w-full items-center',
                    active ? 'flex' : 'hidden group-data-[workflow-tree-dragging=true]/tree:flex'
                )}
            >
                <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className={cn('w-full border-dashed text-muted-foreground', highlighted && 'bg-fill-selected')}
                    onDragOver={handleDragOver}
                    onDragLeave={() => setHighlighted(false)}
                    onDrop={handleDrop}
                    data-attr="workflow-tree-dropzone"
                >
                    <IconPlus />
                    {isBranchJoin ? 'Drop after all paths' : 'Drop step here'}
                </Button>
                <div
                    aria-hidden="true"
                    className="absolute -inset-y-3 inset-x-0 z-10"
                    onDragOver={handleDragOver}
                    onDragLeave={() => setHighlighted(false)}
                    onDrop={handleDrop}
                    data-workflow-tree-dropzone-hit-area
                />
            </div>
        </div>
    )
}
