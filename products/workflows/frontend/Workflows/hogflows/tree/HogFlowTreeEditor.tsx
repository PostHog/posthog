import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { DragEvent } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { ScrollArea, ScrollBar } from 'lib/ui/quill'

import { setHogFlowDragImage } from '../dragPreview'
import { useHogFlowBranchSelection } from '../HogFlowBranchSelection'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import type { HogFlowEdge } from '../types'
import { HogFlowTreeDropzone } from './HogFlowTreeDropzone'
import { HogFlowTreeFeaturePreview } from './HogFlowTreeFeaturePreview'
import { HogFlowTreeNode } from './HogFlowTreeNode'
import { buildWorkflowTree } from './workflowTree'
import { findWorkflowTreePath, getWorkflowTreeBranchSummary, getWorkflowTreeStepIds } from './workflowTreePresentation'

export function HogFlowTreeEditor(): JSX.Element {
    const { nodeToBeAdded, workflow } = useValues(hogFlowEditorLogic)
    const { setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const { setSelectedBranch } = useHogFlowBranchSelection()
    const [focusedEdge, setFocusedEdge] = useState<HogFlowEdge | null>(null)
    const [scrollTarget, setScrollTarget] = useState<string | null>(null)
    const treeRef = useRef<HTMLDivElement>(null)
    const draggedActionIdRef = useRef<string | null>(null)
    const [draggedActionId, setDraggedActionId] = useState<string | null>(null)
    const draggedStepRef = useRef<HTMLElement | null>(null)
    const closestDropzoneRef = useRef<HTMLElement | null>(null)
    const dragStartYRef = useRef<number | null>(null)
    const tree = useMemo(() => buildWorkflowTree(workflow), [workflow])
    const focusedPath = useMemo(() => (focusedEdge ? findWorkflowTreePath(tree, focusedEdge) : []), [tree, focusedEdge])
    const focused = focusedPath.at(-1)
    const activeDropzones = !!nodeToBeAdded

    const focusBranch = (edge: HogFlowEdge): void => {
        setSelectedBranch(null)
        setSelectedNodeId(null)
        setFocusedEdge(edge)
    }

    const returnToWorkflow = (actionId: string): void => {
        setFocusedEdge(null)
        setScrollTarget(actionId)
    }

    // A path inside the focused view can join at a step that the focused view also shows, so leave
    // focus only for a join that the user cannot already see.
    const returnToWorkflowIfOutsideFocus = (actionId: string): void => {
        if (focused && !getWorkflowTreeStepIds(focused.branch.sequence).has(actionId)) {
            returnToWorkflow(actionId)
        }
    }

    const selectContinuation = (actionId: string): void => {
        setSelectedBranch(null)
        setSelectedNodeId(actionId)
        returnToWorkflow(actionId)
    }

    useEffect(() => {
        if (scrollTarget) {
            document.getElementById(`workflow-tree-step-${scrollTarget}`)?.scrollIntoView({ block: 'center' })
            setScrollTarget(null)
        }
    }, [scrollTarget])

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
            setHogFlowDragImage(event.dataTransfer, dragPreviewElement)
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
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <HogFlowTreeFeaturePreview />
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
                    {focused && (
                        <LemonCard hoverEffect={false} className="mb-3 p-3">
                            <LemonButton
                                type="tertiary"
                                size="small"
                                onClick={() => returnToWorkflow(focused.node.action.id)}
                                data-attr="workflow-tree-exit-focus"
                            >
                                Back to workflow
                            </LemonButton>
                            <p className="my-2 break-words text-xs text-secondary">
                                {focusedPath
                                    .map(({ node, branch }) => `${node.action.name} › ${branch.label}`)
                                    .join(' › ')}
                            </p>
                            <h3 className="mb-1">{focused.branch.label}</h3>
                            <p className="mb-0 break-words text-xs text-secondary">
                                {getWorkflowTreeBranchSummary(focused.node, focused.branch)}
                            </p>
                        </LemonCard>
                    )}
                    {(focused?.branch.sequence ?? tree).nodes.map((node) => (
                        <HogFlowTreeNode
                            key={node.action.id}
                            node={node}
                            activeDropzones={activeDropzones}
                            draggedActionId={draggedActionId}
                            draggedActionIdRef={draggedActionIdRef}
                            onDragStart={onDragStart}
                            onDragEnd={onDragEnd}
                            onFocusBranch={focusBranch}
                            onSelectContinuation={focused ? returnToWorkflowIfOutsideFocus : undefined}
                        />
                    ))}
                    {focused?.branch.sequence.trailingEdge && (
                        <HogFlowTreeDropzone
                            active={activeDropzones}
                            draggedActionId={draggedActionId}
                            draggedActionIdRef={draggedActionIdRef}
                            onDragEnd={onDragEnd}
                            edge={focused.branch.sequence.trailingEdge}
                            insertionLabel={`Add step to ${focused.branch.label}`}
                        />
                    )}
                    {focused?.node.joinAction && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            className="self-start max-w-full mt-3"
                            onClick={() => selectContinuation(focused.node.joinAction!.id)}
                            data-attr="workflow-tree-focus-continuation"
                        >
                            <span className="break-words whitespace-normal">{`Continue to: ${focused.node.joinAction.name}`}</span>
                        </LemonButton>
                    )}
                </div>
                <ScrollBar orientation="vertical" />
            </ScrollArea>
        </div>
    )
}
