import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { DragEvent } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ScrollArea, ScrollBar } from 'lib/ui/quill'

import { setHogFlowDragImage } from '../dragPreview'
import { useHogFlowBranchSelection } from '../HogFlowBranchSelection'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import type { HogFlowEdge } from '../types'
import { HogFlowTreeBreadcrumbs } from './HogFlowTreeBreadcrumbs'
import { HogFlowTreeDropzone } from './HogFlowTreeDropzone'
import { HogFlowTreeFeaturePreview } from './HogFlowTreeFeaturePreview'
import { HogFlowTreeFocusHeader } from './HogFlowTreeFocusHeader'
import { HogFlowTreeNode } from './HogFlowTreeNode'
import { HogFlowTreeOutline } from './HogFlowTreeOutline'
import { HogFlowTreePositionBar } from './HogFlowTreePositionBar'
import { useWorkflowTreeScrollSpy } from './useWorkflowTreeScrollSpy'
import { buildWorkflowTree, type WorkflowTreeSequence } from './workflowTree'
import { buildWorkflowTreeOutline, type WorkflowTreeOutlineRow } from './workflowTreeOutline'
import {
    collectWorkflowTreeBranchingOccurrences,
    findWorkflowTreePath,
    getWorkflowTreeBranchKey,
    getWorkflowTreeContinuationPath,
    getWorkflowTreeDefaultCollapsedBranches,
    getWorkflowTreeOccurrenceKey,
    getWorkflowTreePathHeaderId,
    getWorkflowTreeStepId,
    WORKFLOW_TREE_BRANCH_LIMIT,
    type WorkflowTreeNodeViewState,
} from './workflowTreePresentation'

// The position bar covers the top of the scroll area, so the scroll spy skips the step under it.
const POSITION_BAR_OFFSET_PX = 40

interface FocusTarget {
    id: string
    block: ScrollLogicalPosition
}

export function HogFlowTreeEditor(): JSX.Element {
    const { nodeToBeAdded, workflow, treeLayoutVariant } = useValues(hogFlowEditorLogic)
    const { setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const { setSelectedBranch } = useHogFlowBranchSelection()
    const [focusedEdges, setFocusedEdges] = useState<HogFlowEdge[]>([])
    const [focusTarget, setFocusTarget] = useState<FocusTarget | null>(null)
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
    const showNavigator = treeLayoutVariant === 'navigator'
    const hasBranching = useMemo(() => collectWorkflowTreeBranchingOccurrences(tree).length > 0, [tree])
    const outlineRows = useMemo(() => (showNavigator ? buildWorkflowTreeOutline(tree) : []), [tree, showNavigator])
    const activeStepId = useWorkflowTreeScrollSpy(treeRef, showNavigator && !focused, POSITION_BAR_OFFSET_PX, tree)
    const activeRow = activeStepId ? outlineRows.find((row) => row.targetId === activeStepId) : undefined
    const ancestors = activeRow ? findWorkflowTreePath(tree, activeRow.path) : []

    const updateViewState = (key: string, state: WorkflowTreeNodeViewState): void => {
        setViewStates((current) => ({ ...current, [key]: { ...current[key], ...state } }))
    }

    const setPathsHidden = (sequence: WorkflowTreeSequence, rootPath: HogFlowEdge[], hidden: boolean): void => {
        setViewStates((current) => {
            const next = { ...current }
            for (const { node, path } of collectWorkflowTreeBranchingOccurrences(sequence, rootPath)) {
                const key = getWorkflowTreeOccurrenceKey(node.action.id, path)
                next[key] = {
                    ...next[key],
                    branchesOpen: true,
                    collapsedBranches: hidden
                        ? new Set(node.branches.map((branch) => getWorkflowTreeBranchKey(branch.edge)))
                        : new Set(),
                }
            }
            return next
        })
    }

    const focusBranch = (edges: HogFlowEdge[]): void => {
        setSelectedBranch(null)
        setSelectedNodeId(null)
        setFocusedEdges(edges)
        setFocusTarget({ id: 'workflow-tree-exit-focus', block: 'nearest' })
    }

    // Opens every path along `path` that the screen rooted at `screenDepth` shows. Paths above that
    // screen keep their own state, because the user cannot see them from there.
    const revealPath = (path: HogFlowEdge[], screenDepth: number): void => {
        for (const [index, { node, branch }] of findWorkflowTreePath(tree, path).entries()) {
            if (index < screenDepth) {
                continue
            }
            const key = getWorkflowTreeOccurrenceKey(node.action.id, path.slice(0, index))
            const collapsedBranches = new Set(
                viewStates[key]?.collapsedBranches ??
                    getWorkflowTreeDefaultCollapsedBranches(node, index - screenDepth, treeLayoutVariant)
            )
            collapsedBranches.delete(getWorkflowTreeBranchKey(branch.edge))
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

    const focusLevel = (depth: number): void => {
        if (!focused) {
            return
        }
        const returnTarget = getWorkflowTreePathHeaderId(focused.node.action.id, focusedEdges)
        revealPath(focusedEdges.slice(0, -1), depth)
        setFocusedEdges(focusedEdges.slice(0, depth))
        setFocusTarget({ id: returnTarget, block: 'nearest' })
    }

    const returnToWorkflow = (): void => focusLevel(0)

    const selectContinuation = (actionId: string, path: HogFlowEdge[]): void => {
        setSelectedBranch(null)
        setSelectedNodeId(actionId)
        const destinationPath = getWorkflowTreeContinuationPath(tree, path, actionId)
        // A path inside the focused view can join at a step that the focused view also shows, so leave
        // focus only for a join that the user cannot already see.
        const leavesFocus =
            !!focused &&
            getWorkflowTreeOccurrenceKey(actionId, destinationPath.slice(0, focusedEdges.length)) !==
                getWorkflowTreeOccurrenceKey(actionId, focusedEdges)
        revealPath(destinationPath, focused && !leavesFocus ? focusedEdges.length : 0)
        if (leavesFocus) {
            setFocusedEdges([])
        }
        setFocusTarget({ id: getWorkflowTreeStepId(actionId, destinationPath), block: 'nearest' })
    }

    const selectOutlineRow = (row: WorkflowTreeOutlineRow): void => {
        if (focused) {
            setFocusedEdges([])
        }
        revealPath(row.path, 0)
        if (row.kind === 'step') {
            setSelectedBranch(null)
            setSelectedNodeId(row.node.action.id)
        }
        setFocusTarget({ id: row.targetId, block: 'start' })
    }

    const selectAncestor = (index: number): void => {
        const ancestor = ancestors[index]
        if (!activeRow || !ancestor) {
            return
        }
        setFocusTarget({
            id: getWorkflowTreePathHeaderId(ancestor.node.action.id, activeRow.path.slice(0, index + 1)),
            block: 'start',
        })
    }

    useEffect(() => {
        if (!focusTarget) {
            return
        }
        const frame = requestAnimationFrame(() => {
            const target = document.getElementById(focusTarget.id)
            const control = target instanceof HTMLButtonElement ? target : target?.querySelector('button')
            control?.focus({ preventScroll: true })
            target?.scrollIntoView({ block: focusTarget.block })
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

    const renderOutline = (onNavigate?: () => void): JSX.Element => (
        <HogFlowTreeOutline
            rows={outlineRows}
            activeTargetId={activeStepId}
            onSelectRow={(row) => {
                onNavigate?.()
                selectOutlineRow(row)
            }}
            onSetAllPathsHidden={(hidden) => {
                onNavigate?.()
                setPathsHidden(tree, [], hidden)
            }}
            // The rail needs room beside the tree and the side panel, so it hides below the width where all three fit.
            className={
                onNavigate ? undefined : 'w-60 shrink-0 border-e bg-surface-primary @max-[84rem]/workflow-editor:hidden'
            }
        />
    )

    return (
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <HogFlowTreeFeaturePreview />
            <div className="flex min-h-0 min-w-0 flex-1">
                {showNavigator && renderOutline()}
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
                        {showNavigator && !focused && (
                            <HogFlowTreePositionBar
                                ancestors={ancestors}
                                onSelectAncestor={selectAncestor}
                                renderOutline={renderOutline}
                            />
                        )}
                        {treeLayoutVariant === 'closed' && !focused && hasBranching && (
                            <div className="mb-2 flex flex-wrap justify-end gap-1">
                                <LemonButton
                                    type="tertiary"
                                    size="xsmall"
                                    onClick={() => setPathsHidden(tree, [], false)}
                                    data-attr="workflow-tree-show-all-paths"
                                >
                                    Show all paths
                                </LemonButton>
                                <LemonButton
                                    type="tertiary"
                                    size="xsmall"
                                    onClick={() => setPathsHidden(tree, [], true)}
                                    data-attr="workflow-tree-hide-all-paths"
                                >
                                    Hide all paths
                                </LemonButton>
                            </div>
                        )}
                        {focused &&
                            (treeLayoutVariant === 'drilldown' ? (
                                <HogFlowTreeBreadcrumbs focusedPath={focusedPath} onNavigate={focusLevel} />
                            ) : (
                                <HogFlowTreeFocusHeader
                                    focusedPath={focusedPath}
                                    onReturnToWorkflow={returnToWorkflow}
                                />
                            ))}
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
                                onSetPathsHidden={setPathsHidden}
                                path={focused ? focusedEdges : []}
                                depth={0}
                                variant={treeLayoutVariant}
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
                                onClick={() =>
                                    selectContinuation(focused.node.joinAction!.id, focusedEdges.slice(0, -1))
                                }
                                data-attr="workflow-tree-focus-continuation"
                            >
                                <span className="break-words whitespace-normal">{`Continue to: ${focused.node.joinAction.name}`}</span>
                            </LemonButton>
                        )}
                    </div>
                    <ScrollBar orientation="vertical" />
                </ScrollArea>
            </div>
        </div>
    )
}
