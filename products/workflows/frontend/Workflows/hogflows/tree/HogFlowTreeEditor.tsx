import { useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'
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
    const closestDropzoneRef = useRef<HTMLElement | null>(null)
    const dragStartYRef = useRef<number | null>(null)
    const tree = useMemo(() => buildWorkflowTree(workflow), [workflow])
    const activeDropzones = !!nodeToBeAdded

    const clearClosestDropzone = (): void => {
        closestDropzoneRef.current?.removeAttribute('data-workflow-tree-dropzone-closest')
        closestDropzoneRef.current = null
    }

    useEffect(() => {
        if (!activeDropzones) {
            clearClosestDropzone()
        }
    }, [activeDropzones])

    const onDragStart = (
        event: DragEvent<HTMLDivElement>,
        actionId: string,
        dragPreviewElement: HTMLDivElement | null
    ): void => {
        event.dataTransfer.effectAllowed = 'move'
        event.dataTransfer.setData('text/plain', actionId)
        dragStartYRef.current = event.clientY
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

    const onTreeDragOver = (event: DragEvent<HTMLDivElement>): void => {
        if (!draggedActionIdRef.current && !activeDropzones) {
            return
        }

        event.preventDefault()
        if (dragStartYRef.current !== null && Math.abs(event.clientY - dragStartYRef.current) < 16) {
            clearClosestDropzone()
            return
        }

        const candidates = Array.from(
            treeRef.current?.querySelectorAll<HTMLElement>('[data-workflow-tree-dropzone-candidate]') ?? []
        ).filter((candidate) => {
            if (candidate.dataset.workflowTreeDropzoneDisabled === 'true') {
                return false
            }

            let ancestor: HTMLElement | null = candidate
            while (ancestor) {
                if (ancestor.dataset.workflowTreeBranchContent === draggedActionIdRef.current) {
                    return false
                }
                ancestor = ancestor.parentElement
            }
            return true
        })
        const closestDropzone = candidates.reduce<HTMLElement | null>((closest, candidate) => {
            if (!closest) {
                return candidate
            }
            const closestCenter = closest.getBoundingClientRect().top + closest.getBoundingClientRect().height / 2
            const candidateCenter = candidate.getBoundingClientRect().top + candidate.getBoundingClientRect().height / 2
            return Math.abs(event.clientY - candidateCenter) < Math.abs(event.clientY - closestCenter)
                ? candidate
                : closest
        }, null)

        if (closestDropzone !== closestDropzoneRef.current) {
            clearClosestDropzone()
            closestDropzone?.setAttribute('data-workflow-tree-dropzone-closest', 'true')
            closestDropzoneRef.current = closestDropzone
        }
    }

    const onTreeDropCapture = (event: DragEvent<HTMLDivElement>): void => {
        const nativeEvent = event.nativeEvent as globalThis.DragEvent & { workflowTreeNearestDrop?: boolean }
        if (nativeEvent.workflowTreeNearestDrop) {
            return
        }

        event.preventDefault()
        event.stopPropagation()
        const closestDropzone = closestDropzoneRef.current
        if (!closestDropzone) {
            onDragEnd()
            return
        }

        const dropEvent = new window.DragEvent('drop', {
            bubbles: true,
            cancelable: true,
            clientX: event.clientX,
            clientY: event.clientY,
            dataTransfer: event.dataTransfer,
        }) as globalThis.DragEvent & { workflowTreeNearestDrop?: boolean }
        dropEvent.workflowTreeNearestDrop = true
        closestDropzone.querySelector<HTMLElement>('[data-attr="workflow-tree-dropzone"]')?.dispatchEvent(dropEvent)
    }

    const onDragEnd = (): void => {
        clearClosestDropzone()
        dragStartYRef.current = null
        treeRef.current?.removeAttribute('data-workflow-tree-dragging')
        draggedStepRef.current?.removeAttribute('data-workflow-tree-dragging')
        draggedStepRef.current = null
        draggedActionIdRef.current = null
        setDraggedActionId(null)
    }

    return (
        <ScrollArea
            className="min-h-0 min-w-0 flex-1 bg-background @max-[48rem]/workflow-editor:min-h-80 @max-[48rem]/workflow-editor:shrink-0"
            data-quill
            data-attr="workflow-tree-editor"
        >
            <div
                ref={treeRef}
                className="group/tree mx-auto flex w-full max-w-3xl flex-col p-4"
                onDragOver={onTreeDragOver}
                onDropCapture={onTreeDropCapture}
            >
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
