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
}: {
    active: boolean
    draggedActionId: string | null
    edge: HogFlowEdge
    isBranchJoin?: boolean
}): JSX.Element {
    const { moveNodeToEdge, onDragOver, onDrop, setHighlightedDropzoneNodeId } = useActions(hogFlowEditorLogic)
    const [highlighted, setHighlighted] = useState(false)
    const isNoOpTarget =
        !!draggedActionId && (edge.to === draggedActionId || (!isBranchJoin && edge.from === draggedActionId))

    return (
        <div className="flex h-7 w-full items-center justify-center">
            {!active || isNoOpTarget ? (
                <span className="h-full border-s border-border" aria-hidden="true" />
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
