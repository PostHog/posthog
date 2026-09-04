import { useActions, useValues } from 'kea'
import { useState } from 'react'
import type { DragEvent } from 'react'

import { IconPlus } from '@posthog/icons'

import { Button, cn } from 'lib/ui/quill'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import type { HogFlowEdge } from '../types'
import { computeMoveTreeBranchEdges, isBranchingAction } from './workflowTree'

export function HogFlowTreeDropzone({
    active,
    draggedActionId,
    edge,
    isBranchJoin = false,
    showConnector = true,
    compact = false,
}: {
    active: boolean
    draggedActionId: string | null
    edge: HogFlowEdge
    isBranchJoin?: boolean
    showConnector?: boolean
    compact?: boolean
}): JSX.Element {
    const { workflow } = useValues(hogFlowEditorLogic)
    const { moveNodeToEdge, onDragOver, onDrop, setHighlightedDropzoneNodeId, setSelectedNodeId, setWorkflowInfo } =
        useActions(hogFlowEditorLogic)
    const [highlighted, setHighlighted] = useState(false)
    const isNoOpTarget =
        !!draggedActionId && (edge.to === draggedActionId || (!isBranchJoin && edge.from === draggedActionId))
    const handleDragOver = (event: DragEvent<HTMLElement>): void => {
        setHighlighted(true)
        onDragOver(event)
    }
    const handleDrop = (event: DragEvent<HTMLElement>): void => {
        setHighlighted(false)
        if (draggedActionId) {
            const action = workflow.actions.find((action) => action.id === draggedActionId)
            if (!action || !isBranchingAction(action)) {
                moveNodeToEdge(draggedActionId, edge, isBranchJoin)
            } else {
                const newEdges = computeMoveTreeBranchEdges(workflow, draggedActionId, edge, isBranchJoin)
                if (newEdges) {
                    setWorkflowInfo({ actions: workflow.actions, edges: newEdges })
                    setSelectedNodeId(draggedActionId)
                }
            }
        } else if (isBranchJoin) {
            setHighlightedDropzoneNodeId(`dropzone_target_${edge.to}_branch_join`)
            onDrop(event)
        } else {
            onDrop(event, edge)
        }
    }

    return (
        <div className={cn('flex w-full items-center justify-center', compact && !active ? 'h-2' : 'h-7')}>
            {!active || isNoOpTarget ? (
                showConnector && (
                    <svg
                        className="h-full w-4 text-muted-foreground opacity-60"
                        viewBox="0 0 16 28"
                        fill="none"
                        aria-hidden="true"
                    >
                        <path d="M8 0v20m-5-2 5 5 5-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                    </svg>
                )
            ) : (
                <div className="relative flex h-full w-full items-center">
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
                        Drop step here
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
            )}
        </div>
    )
}
