import { useValues } from 'kea'
import { useMemo, useRef } from 'react'
import type { DragEvent } from 'react'

import { ScrollArea, ScrollBar } from 'lib/ui/quill'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowTreeNode } from './HogFlowTreeNode'
import { buildWorkflowTree } from './workflowTree'

export function HogFlowTreeEditor(): JSX.Element {
    const { nodeToBeAdded, workflow } = useValues(hogFlowEditorLogic)
    const treeRef = useRef<HTMLDivElement>(null)
    const draggedActionIdRef = useRef<string | null>(null)
    const draggedStepRef = useRef<HTMLElement | null>(null)
    const tree = useMemo(() => buildWorkflowTree(workflow), [workflow])
    const activeDropzones = !!nodeToBeAdded

    const onDragStart = (event: DragEvent<HTMLDivElement>, actionId: string): void => {
        event.dataTransfer.effectAllowed = 'move'
        event.dataTransfer.setData('text/plain', actionId)
        const step = event.currentTarget.closest('[data-attr="workflow-tree-step"]')
        if (step instanceof HTMLElement && typeof event.dataTransfer.setDragImage === 'function') {
            event.dataTransfer.setDragImage(step, 0, step.getBoundingClientRect().height / 2)
            step.dataset.workflowTreeDragging = 'true'
            draggedStepRef.current = step
        }
        draggedActionIdRef.current = actionId
        treeRef.current?.setAttribute('data-workflow-tree-dragging', 'true')
    }

    const onDragEnd = (): void => {
        treeRef.current?.removeAttribute('data-workflow-tree-dragging')
        draggedStepRef.current?.removeAttribute('data-workflow-tree-dragging')
        draggedStepRef.current = null
        draggedActionIdRef.current = null
    }

    return (
        <ScrollArea className="min-h-0 min-w-0 flex-1 bg-background" data-quill data-attr="workflow-tree-editor">
            <div ref={treeRef} className="group/tree mx-auto flex w-full max-w-3xl flex-col p-4">
                {tree.nodes.map((node) => (
                    <HogFlowTreeNode
                        key={node.action.id}
                        node={node}
                        activeDropzones={activeDropzones}
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
