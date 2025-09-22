import {
    Active,
    DndContext,
    DragOverlay,
    KeyboardSensor,
    MeasuringStrategy,
    MouseSensor,
    Over,
    TouchSensor,
    UniqueIdentifier,
    closestCorners,
    useDroppable,
    useSensor,
    useSensors,
} from '@dnd-kit/core'
import {
    SortableContext,
    arrayMove,
    sortableKeyboardCoordinates,
    useSortable,
    verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import React, { PropsWithChildren, useEffect, useRef, useState } from 'react'

import { IconGear, IconPlus } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { tasksLogic } from '../tasksLogic'
import { Task, TaskWorkflow, WorkflowStage } from './../types'
import { TaskCard } from './TaskCard'
import { WorkflowBuilder } from './WorkflowBuilder'
import { workflowSettingsLogic } from './workflowSettingsLogic'

function DroppableContainer({
    children,
    disabled,
    id,
}: PropsWithChildren<{
    disabled?: boolean
    id: UniqueIdentifier
}>): JSX.Element {
    const { setNodeRef, isOver } = useDroppable({ id, data: { type: 'container' } })

    return (
        <div
            ref={disabled ? undefined : setNodeRef}
            className={cn(
                'space-y-2 min-h-[200px] rounded-md',
                isOver && !disabled && 'ring-2 ring-primary/40 bg-primary/5',
                disabled && 'opacity-50 pointer-events-none'
            )}
        >
            {children}
        </div>
    )
}

type Items = Record<UniqueIdentifier, Task[]>

export function KanbanView(): JSX.Element {
    const { tasks, workflowKanbanData } = useValues(tasksLogic)
    const { openTaskDetail, moveTask } = useActions(tasksLogic)
    const { loadWorkflows } = useActions(workflowSettingsLogic)

    const [activeTask, setActiveTask] = useState<Task | null>(null)
    const [collapsedWorkflows, setCollapsedWorkflows] = useState<Set<string>>(new Set())
    const [clonedItems, setClonedItems] = useState<Items | null>(null)
    const [dropIndicator, setDropIndicator] = useState<{ container: UniqueIdentifier | null; index: number | null }>({
        container: null,
        index: null,
    })
    const [showCreateWorkflow, setShowCreateWorkflow] = useState(false)
    const [editingWorkflow, setEditingWorkflow] = useState<TaskWorkflow | null>(null)
    const recentlyMovedToNewContainer = useRef(false)

    const [items, setItems] = useState<Items>({})

    useEffect(() => {
        const newItems: Items = {}
        workflowKanbanData.forEach(({ workflow, stages }) => {
            stages.forEach(({ stage, tasks }) => {
                newItems[`${workflow.id}-${stage.key}`] = tasks
            })
        })
        setItems(newItems)
    }, [workflowKanbanData])

    const toggleWorkflow = (workflowId: string): void => {
        const newCollapsed = new Set(collapsedWorkflows)
        if (newCollapsed.has(workflowId)) {
            newCollapsed.delete(workflowId)
        } else {
            newCollapsed.add(workflowId)
        }
        setCollapsedWorkflows(newCollapsed)
    }

    const handleTaskClick = (taskId: Task['id']): void => {
        openTaskDetail(taskId)
    }

    const sensors = useSensors(
        useSensor(MouseSensor, { activationConstraint: { distance: 8 } }),
        useSensor(TouchSensor, { activationConstraint: { delay: 150, tolerance: 5 } }),
        useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
    )
    const findContainer = (item: Active | Over): UniqueIdentifier => {
        if (isContainer(item)) {
            return item.id
        }
        const task = tasks.find((t: Task) => t.id === item.id)
        if (!task) {
            return ''
        }

        for (const { workflow, stages } of workflowKanbanData) {
            for (const { stage } of stages) {
                if (task.workflow === workflow.id && task.current_stage === stage.id) {
                    return `${workflow.id}-${stage.key}`
                }
            }
        }
        return ''
    }

    const findStageByContainerId = (
        targetContainerId: string
    ): { workflow: TaskWorkflow; stage: WorkflowStage } | null => {
        for (const workflowData of workflowKanbanData) {
            for (const stageData of workflowData.stages) {
                const expectedContainerId = `${workflowData.workflow.id}-${stageData.stage.key}`
                if (expectedContainerId === targetContainerId) {
                    return { workflow: workflowData.workflow, stage: stageData.stage }
                }
            }
        }
        return null
    }

    const canDropTask = (activeTask: Task, targetContainerId: string): boolean => {
        const target = findStageByContainerId(targetContainerId)
        if (!target) {
            return false
        }

        if (activeTask.workflow !== target.workflow.id) {
            return false
        }

        return true
    }

    const onDragCancel = (): void => {
        if (clonedItems) {
            setItems(clonedItems)
        }

        setActiveTask(null)
        setClonedItems(null)
    }

    useEffect(() => {
        requestAnimationFrame(() => {
            recentlyMovedToNewContainer.current = false
        })
    }, [items])

    if (showCreateWorkflow || editingWorkflow) {
        return (
            <WorkflowBuilder
                workflow={editingWorkflow || undefined}
                onSave={() => {
                    setShowCreateWorkflow(false)
                    setEditingWorkflow(null)
                    loadWorkflows()
                }}
                onCancel={() => {
                    setShowCreateWorkflow(false)
                    setEditingWorkflow(null)
                }}
            />
        )
    }

    return (
        <div className="space-y-4">
            {/* Workflow Management Header */}
            <div className="flex justify-between items-center">
                <div>
                    <h2 className="text-xl font-semibold">Workflows</h2>
                </div>
                <LemonButton type="primary" icon={<IconPlus />} onClick={() => setShowCreateWorkflow(true)}>
                    New Workflow
                </LemonButton>
            </div>
            <DndContext
                sensors={sensors}
                collisionDetection={closestCorners}
                measuring={{ droppable: { strategy: MeasuringStrategy.Always } }}
                onDragStart={({ active }) => {
                    const task = tasks.find((t: Task) => t.id === active.id)
                    if (task) {
                        setActiveTask(task)
                        setClonedItems(items)
                    }
                }}
                onDragOver={({ active, over, delta }) => {
                    if (!over || !activeTask) {
                        return
                    }

                    const activeContainer = findContainer(active)
                    const overContainer = findContainer(over)
                    if (!activeContainer || !overContainer) {
                        return
                    }

                    // Check if drop is allowed
                    if (!canDropTask(activeTask, String(overContainer))) {
                        setDropIndicator({ container: null, index: null })
                        return
                    }

                    // Show insertion indicator only; no list mutation

                    const targetItems = items[overContainer]

                    const overId = String(over.id)
                    const overIndex = targetItems.findIndex((i: Task) => i.id === overId)
                    const putBelowLast = overIndex === targetItems.length - 1 && (delta?.y || 0) > 0
                    const newIndex = overIndex >= 0 ? overIndex + (putBelowLast ? 1 : 0) : targetItems.length

                    setDropIndicator({ container: overContainer, index: newIndex })
                }}
                onDragEnd={({ active, over }) => {
                    const activeContainer = findContainer(active)

                    if (!activeContainer) {
                        setActiveTask(null)
                        return
                    }

                    if (over == null) {
                        setActiveTask(null)
                        setDropIndicator({ container: null, index: null })
                        return
                    }

                    const overContainer = findContainer(over)

                    if (overContainer && activeTask && canDropTask(activeTask, String(overContainer))) {
                        const sourceItems = items[activeContainer]
                        const targetItems = items[overContainer]
                        const sourceIndex = sourceItems.findIndex((t: Task) => t.id === active.id)
                        const overIndexRaw = targetItems.findIndex((t: Task) => t.id === over.id)

                        if (activeContainer === overContainer) {
                            const fallbackIndex =
                                dropIndicator.container === overContainer && dropIndicator.index != null
                                    ? dropIndicator.index
                                    : targetItems.length
                            const finalIndex = overIndexRaw >= 0 ? overIndexRaw : fallbackIndex

                            if (sourceIndex >= 0 && finalIndex != null && sourceIndex !== finalIndex) {
                                setItems((current) => ({
                                    ...current,
                                    [overContainer]: arrayMove(current[overContainer], sourceIndex, finalIndex),
                                }))
                                // Get the actual stage key from the target container
                                const target = findStageByContainerId(String(overContainer))
                                if (target) {
                                    moveTask(String(active.id), target.stage.key, finalIndex)
                                }
                            }
                        } else {
                            const draggedTask =
                                sourceIndex >= 0
                                    ? sourceItems[sourceIndex]
                                    : tasks.find((t: Task) => t.id === active.id)
                            if (!draggedTask) {
                                setActiveTask(null)
                                return
                            }

                            const insertIndex =
                                overIndexRaw >= 0
                                    ? overIndexRaw
                                    : dropIndicator.container === overContainer && dropIndicator.index != null
                                      ? dropIndicator.index
                                      : targetItems.length

                            setItems((current) => ({
                                ...current,
                                [activeContainer]: current[activeContainer].filter((t) => t.id !== active.id),
                                [overContainer]: [
                                    ...current[overContainer].slice(0, insertIndex),
                                    { ...draggedTask },
                                    ...current[overContainer].slice(insertIndex),
                                ],
                            }))

                            // Get the actual stage key from the target container
                            const target = findStageByContainerId(String(overContainer))
                            if (target) {
                                moveTask(String(active.id), target.stage.key, insertIndex)
                            }
                        }
                    } else {
                        // Drop not allowed - reset to original state
                        if (clonedItems) {
                            setItems(clonedItems)
                        }
                    }

                    setActiveTask(null)
                    setDropIndicator({ container: null, index: null })
                }}
                onDragCancel={onDragCancel}
            >
                <div className="space-y-6">
                    {workflowKanbanData.map(({ workflow, stages }) => {
                        const isCollapsed = collapsedWorkflows.has(workflow.id)
                        const totalTasks = stages.reduce((sum, { tasks }) => sum + tasks.length, 0)

                        return (
                            <div key={workflow.id} className="bg-bg-light rounded-lg border border-border">
                                {/* Workflow Header */}
                                <div className="flex items-center justify-between p-4">
                                    <div
                                        className="flex items-center gap-3 cursor-pointer hover:bg-bg-3000 rounded px-2 py-1 -mx-2 -my-1 flex-1"
                                        onClick={() => toggleWorkflow(workflow.id)}
                                    >
                                        <div
                                            className="w-4 h-4 rounded-full"
                                            style={{ backgroundColor: workflow.color }}
                                        />
                                        <h2 className="text-lg font-semibold">{workflow.name}</h2>
                                        <span className="text-sm text-muted">({totalTasks} tasks)</span>
                                        <div className="text-muted ml-auto">{isCollapsed ? '▶' : '▼'}</div>
                                    </div>
                                </div>

                                {/* Workflow Stages */}
                                {!isCollapsed && (
                                    <div className="px-4 pb-4">
                                        <div className="flex items-center justify-between py-2">
                                            <div />
                                            <LemonButton
                                                size="small"
                                                type="secondary"
                                                icon={<IconGear />}
                                                onClick={(e) => {
                                                    e.stopPropagation()
                                                    setEditingWorkflow(workflow)
                                                }}
                                                tooltip="Edit workflow"
                                            />
                                        </div>
                                        <div
                                            className="grid gap-4"
                                            style={{
                                                gridTemplateColumns: `repeat(${stages.length}, minmax(250px, 1fr))`,
                                            }}
                                        >
                                            {stages.map(({ stage, tasks: stageTasks }) => {
                                                const containerId = `${workflow.id}-${stage.key}`
                                                const isAgentOnly = !stage.is_manual_only

                                                return (
                                                    <div
                                                        key={containerId}
                                                        className={cn(
                                                            'bg-white rounded-lg p-3 relative border border-border'
                                                        )}
                                                    >
                                                        {isAgentOnly && (
                                                            <div className="absolute top-2 right-2 z-10 pointer-events-none">
                                                                <div className="bg-bg-light border border-border rounded-lg px-2 py-1 shadow-sm">
                                                                    <div className="flex items-center gap-1 text-xs text-muted">
                                                                        <span className="w-2 h-2 bg-warning rounded-full" />
                                                                        Agent
                                                                    </div>
                                                                </div>
                                                            </div>
                                                        )}
                                                        <div className="flex justify-between items-center mb-3">
                                                            <div className="flex items-center gap-2">
                                                                <div
                                                                    className="w-3 h-3 rounded-full"
                                                                    style={{ backgroundColor: stage.color }}
                                                                />
                                                                <h3 className="font-medium text-sm">{stage.name}</h3>
                                                            </div>
                                                            <span className="text-xs text-muted bg-border rounded-full px-2 py-1">
                                                                {stageTasks.length}
                                                            </span>
                                                        </div>
                                                        <DroppableContainer
                                                            id={containerId}
                                                            disabled={
                                                                activeTask
                                                                    ? !canDropTask(activeTask, containerId)
                                                                    : false
                                                            }
                                                        >
                                                            <SortableContext
                                                                items={stageTasks.map((t) => t.id)}
                                                                strategy={verticalListSortingStrategy}
                                                            >
                                                                {stageTasks.map((task, idx) => (
                                                                    <React.Fragment key={`row-${task.id}`}>
                                                                        {dropIndicator.container === containerId &&
                                                                            dropIndicator.index === idx && (
                                                                                <DropIndicator />
                                                                            )}
                                                                        <SortableItem
                                                                            key={task.id}
                                                                            task={task}
                                                                            onClick={handleTaskClick}
                                                                        />
                                                                    </React.Fragment>
                                                                ))}
                                                                {dropIndicator.container === containerId &&
                                                                    dropIndicator.index === stageTasks.length && (
                                                                        <DropIndicator />
                                                                    )}
                                                            </SortableContext>
                                                        </DroppableContainer>
                                                    </div>
                                                )
                                            })}
                                        </div>
                                    </div>
                                )}
                            </div>
                        )
                    })}

                    {workflowKanbanData.length === 0 && (
                        <div className="text-center py-12 text-muted">
                            <p className="mb-2">No workflows configured</p>
                            <p className="text-sm">Create a workflow in Settings to see tasks organized by stages</p>
                        </div>
                    )}
                </div>
                <DragOverlay>
                    {activeTask ? (
                        <div className="opacity-90">
                            <TaskCard task={activeTask} draggable />
                        </div>
                    ) : null}
                </DragOverlay>
            </DndContext>
        </div>
    )
}

function SortableItem({
    disabled,
    task,
    onClick,
}: {
    task: Task
    disabled?: boolean
    onClick: (id: Task['id']) => void
}): JSX.Element {
    const { setNodeRef, listeners, transform, attributes, transition, isDragging } = useSortable({
        id: task.id,
        data: { current_stage: task.current_stage },
    })

    return (
        <div
            ref={disabled ? undefined : setNodeRef}
            {...listeners}
            {...attributes}
            style={{
                transform: CSS.Translate.toString(transform),
                transition,
            }}
            className={cn('cursor-grab active:cursor-grabbing', isDragging && 'opacity-50 z-50 relative')}
        >
            <TaskCard task={task} draggable onClick={() => onClick(task.id)} />
        </div>
    )
}

function isContainer(item: Active | Over): boolean {
    return !!(item.data.current && item.data.current.type === 'container')
}

function DropIndicator(): JSX.Element {
    return (
        <LemonCard className="p-3 my-1 border-2 border-dashed border-primary/50 bg-transparent pointer-events-none">
            <div className="flex justify-between items-start mb-2">
                <div className="h-3 w-2/3 bg-border/60 rounded" />
            </div>
            <div className="h-2 w-full bg-border/40 rounded mb-2" />
            <div className="h-2 w-4/5 bg-border/40 rounded mb-3" />
            <div className="flex justify-between items-center">
                <span className="h-5 w-24 rounded-full bg-border/60" />
                <span className="h-6 w-12 rounded bg-border/60" />
            </div>
        </LemonCard>
    )
}
