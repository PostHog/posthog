import { useActions } from 'kea'
import { useState } from 'react'
import type { DragEvent } from 'react'

import { IconPlus } from '@posthog/icons'

import { Button, cn } from 'lib/ui/quill'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import type { HogFlowEdge } from '../types'

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
    const { moveNodeToEdge, onDragOver, onDrop, setHighlightedDropzoneNodeId } = useActions(hogFlowEditorLogic)
    const [highlighted, setHighlighted] = useState(false)
    const isNoOpTarget =
        !!draggedActionId && (edge.to === draggedActionId || (!isBranchJoin && edge.from === draggedActionId))

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
                <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className={cn('w-full border-dashed text-muted-foreground', highlighted && 'bg-fill-selected')}
                    onDragOver={(event: DragEvent<HTMLButtonElement>) => {
                        setHighlighted(true)
                        onDragOver(event)
                    }}
                    onDragLeave={() => setHighlighted(false)}
                    onDrop={(event: DragEvent<HTMLButtonElement>) => {
                        setHighlighted(false)
                        if (draggedActionId) {
                            moveNodeToEdge(draggedActionId, edge, isBranchJoin)
                        } else if (isBranchJoin) {
                            setHighlightedDropzoneNodeId(`dropzone_target_${edge.to}_branch_join`)
                            onDrop(event)
                        } else {
                            onDrop(event, edge)
                        }
                    }}
                    data-attr="workflow-tree-dropzone"
                >
                    <IconPlus />
                    Drop step here
                </Button>
            )}
        </div>
    )
}
