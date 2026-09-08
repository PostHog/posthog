import { useValues } from 'kea'
import { useMemo, useRef, useState } from 'react'
import type { DragEvent } from 'react'

import { ScrollArea, ScrollBar } from 'lib/ui/quill'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { NODE_HEIGHT, NODE_WIDTH } from '../react_flow_utils/constants'
import { HogFlowTreeNode } from './HogFlowTreeNode'
import { buildWorkflowTree } from './workflowTree'

export function HogFlowTreeEditor(): JSX.Element {
    const { nodeToBeAdded, workflow } = useValues(hogFlowEditorLogic)
    const treeRef = useRef<HTMLDivElement>(null)
    const draggedActionIdRef = useRef<string | null>(null)
    const [draggedActionId, setDraggedActionId] = useState<string | null>(null)
    const draggedStepRef = useRef<HTMLElement | null>(null)
    const tree = useMemo(() => buildWorkflowTree(workflow), [workflow])
    const activeDropzones = !!nodeToBeAdded

    const onDragStart = (
        event: DragEvent<HTMLDivElement>,
        actionId: string,
        dragPreviewElement: HTMLDivElement | null
    ): void => {
        event.dataTransfer.effectAllowed = 'move'
        event.dataTransfer.setData('text/plain', actionId)
        const step = event.currentTarget.closest('[data-attr="workflow-tree-step"]')
        if (step instanceof HTMLElement && typeof event.dataTransfer.setDragImage === 'function') {
            if (dragPreviewElement) {
                const dragPreview = dragPreviewElement.cloneNode(true) as HTMLDivElement
                dragPreview.classList.remove('invisible')
                dragPreview.style.position = 'fixed'
                dragPreview.style.left = '0'
                dragPreview.style.top = '0'
                dragPreview.style.width = `${NODE_WIDTH * 1.5}px`
                dragPreview.style.height = `${NODE_HEIGHT * 1.5}px`
                dragPreview.style.transform = 'translate(-101%, -101%)'
                document.body.appendChild(dragPreview)
                event.dataTransfer.setDragImage(dragPreview, (NODE_WIDTH * 3) / 4, (NODE_HEIGHT * 3) / 4)
                window.setTimeout(() => dragPreview.remove())
            }
            step.dataset.workflowTreeDragging = 'true'
            draggedStepRef.current = step
        }
        draggedActionIdRef.current = actionId
        setDraggedActionId(actionId)
        treeRef.current?.setAttribute('data-workflow-tree-dragging', 'true')
    }

    const onDragEnd = (): void => {
        treeRef.current?.removeAttribute('data-workflow-tree-dragging')
        draggedStepRef.current?.removeAttribute('data-workflow-tree-dragging')
        draggedStepRef.current = null
        draggedActionIdRef.current = null
        setDraggedActionId(null)
    }

    return (
        <ScrollArea className="min-h-0 min-w-0 flex-1 bg-background" data-quill data-attr="workflow-tree-editor">
            <div ref={treeRef} className="group/tree mx-auto flex w-full max-w-3xl flex-col p-4">
                {tree.nodes.map((node) => (
                    <HogFlowTreeNode
                        key={node.action.id}
                        node={node}
                        activeDropzones={activeDropzones}
                        draggedActionId={draggedActionId}
                        draggedActionIdRef={draggedActionIdRef}
                        onDragStart={onDragStart}
                        onDragEnd={onDragEnd}
                    />
                ))}
            </div>
            <ScrollBar orientation="vertical" />
        </ScrollArea>
    )
}
