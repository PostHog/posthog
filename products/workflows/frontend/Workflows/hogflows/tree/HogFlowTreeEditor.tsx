import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { DragEvent } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ScrollArea, ScrollBar } from 'lib/ui/quill'

import { setHogFlowDragImage } from '../dragPreview'
import { useHogFlowBranchSelection } from '../HogFlowBranchSelection'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import type { HogFlowEdge } from '../types'
import { HogFlowTreeDropzone } from './HogFlowTreeDropzone'
import { HogFlowTreeFeaturePreview } from './HogFlowTreeFeaturePreview'
import { HogFlowTreeFocusHeader } from './HogFlowTreeFocusHeader'
import { HogFlowTreeNode } from './HogFlowTreeNode'
import { buildWorkflowTree } from './workflowTree'
import {
    findWorkflowTreePath,
    getWorkflowTreeContinuationPath,
    getWorkflowTreeOccurrenceKey,
    getWorkflowTreeStepId,
    WORKFLOW_TREE_BRANCH_LIMIT,
    type WorkflowTreeNodeViewState,
} from './workflowTreePresentation'

export function HogFlowTreeEditor(): JSX.Element {
    const { nodeToBeAdded, workflow } = useValues(hogFlowEditorLogic)
    const { setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const { setSelectedBranch } = useHogFlowBranchSelection()
    const [focusedEdges, setFocusedEdges] = useState<HogFlowEdge[]>([])
    const [focusTarget, setFocusTarget] = useState<string | null>(null)
    const [viewStates, setViewStates] = useState<Record<string, WorkflowTreeNodeViewState>>({})
    const treeRef = useRef<HTMLDivElement>(null)
    const draggedActionIdRef = useRef<string | null>(null)
    const [draggedActionId, setDraggedActionId] = useState<string | null>(null)
    const draggedStepRef = useRef<HTMLElement | null>(null)
    const closestDropzoneRef = useRef<HTMLElement | null>(null)
    const dragStartYRef = useRef<number | null>(null)
    const tree = useMemo(() => buildWorkflowTree(workflow), [workflow])
    const focusedPath = useMemo(() => findWorkflowTreePath(tree, focusedEdges), [tree, focusedEdges])
    const focused = focusedPath.at(-1)
    const activeDropzones = !!nodeToBeAdded

    const updateViewState = (key: string, state: WorkflowTreeNodeViewState): void => {
        setViewStates((current) => ({ ...current, [key]: { ...current[key], ...state } }))
    }

    const focusBranch = (edges: HogFlowEdge[]): void => {
        setSelectedBranch(null)
        setSelectedNodeId(null)
        setFocusedEdges(edges)
        setFocusTarget('workflow-tree-exit-focus')
    }

    const revealPath = (path: HogFlowEdge[]): void => {
        for (const [index, { node, branch }] of findWorkflowTreePath(tree, path).entries()) {
            const key = getWorkflowTreeOccurrenceKey(node.action.id, path.slice(0, index))
            const collapsedBranches = new Set(viewStates[key]?.collapsedBranches)
            collapsedBranches.delete(`${branch.edge.from}-${branch.edge.type}-${branch.edge.index ?? 'continue'}`)
            updateViewState(key, {
                branchesOpen: true,
                showAllBranches:
                    viewStates[key]?.showAllBranches ||
                    node.branches.filter((item) => item.edge.type === 'branch').indexOf(branch) >=
                        WORKFLOW_TREE_BRANCH_LIMIT,
                collapsedBranches,
            })
        }
    }

    const returnToWorkflow = (): void => {
        if (focused) {
            revealPath(focusedEdges.slice(0, -1))
            setFocusedEdges([])
            setFocusTarget(`workflow-tree-path-${getWorkflowTreeOccurrenceKey(focused.node.action.id, focusedEdges)}`)
        }
    }

    const selectContinuation = (actionId: string, path: HogFlowEdge[]): void => {
        setSelectedBranch(null)
        setSelectedNodeId(actionId)
        const destinationPath = getWorkflowTreeContinuationPath(tree, path, actionId)
        revealPath(destinationPath)
        // A path inside the focused view can join at a step that the focused view also shows, so leave
        // focus only for a join that the user cannot already see.
        if (
            focused &&
            getWorkflowTreeOccurrenceKey(actionId, destinationPath.slice(0, focusedEdges.length)) !==
                getWorkflowTreeOccurrenceKey(actionId, focusedEdges)
        ) {
            setFocusedEdges([])
        }
        setFocusTarget(getWorkflowTreeStepId(actionId, destinationPath))
    }

    useEffect(() => {
        if (!focusTarget) {
            return
        }
        const frame = requestAnimationFrame(() => {
            const target = document.getElementById(focusTarget)
            const control = target instanceof HTMLButtonElement ? target : target?.querySelector('button')
            control?.focus({ preventScroll: true })
            target?.scrollIntoView({ block: 'nearest' })
            setFocusTarget(null)
        })
        return () => cancelAnimationFrame(frame)
    }, [focusTarget])

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
                        <HogFlowTreeFocusHeader focusedPath={focusedPath} onReturnToWorkflow={returnToWorkflow} />
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
                            onSelectContinuation={selectContinuation}
                            path={focused ? focusedEdges : []}
                            viewStates={viewStates}
                            onViewStateChange={updateViewState}
                        />
                    ))}
                    {focused?.branch.sequence.trailingEdge && (
                        <HogFlowTreeDropzone
                            active={activeDropzones}
                            draggedActionId={draggedActionId}
                            draggedActionIdRef={draggedActionIdRef}
                            onDragEnd={onDragEnd}
                            edge={focused.branch.sequence.trailingEdge}
                            alwaysVisible={focused.branch.sequence.nodes.length === 0}
                            insertionLabel={`Add step to ${focused.branch.label}`}
                        />
                    )}
                    {focused?.node.joinAction && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            className="self-start max-w-full mt-3"
                            onClick={() => selectContinuation(focused.node.joinAction!.id, focusedEdges.slice(0, -1))}
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
