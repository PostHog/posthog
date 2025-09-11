import {
    Active,
    DndContext,
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

import { LemonCard } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { tasksLogic } from '../tasksLogic'
import { Task, TaskStatus } from './../types'
import { TaskCard } from './TaskCard'
import { TaskModal } from './TaskModal'

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
            className={cn('space-y-2 min-h-[200px] rounded-md', isOver && 'ring-2 ring-primary/40 bg-primary/5')}
        >
            {children}
        </div>
    )
}

type Items = Record<UniqueIdentifier, Task[]>

export function KanbanView(): JSX.Element {
    const { tasks, kanbanColumns, selectedTask } = useValues(tasksLogic)
    const { openTaskModal, closeTaskModal, moveTask } = useActions(tasksLogic)

    const [items, setItems] = useState<Items>(kanbanColumns)
    const [activeTask, setActiveTask] = useState<Task | null>(null)
    const recentlyMovedToNewContainer = useRef(false)

    const containers = Object.keys(kanbanColumns) as UniqueIdentifier[]

    const handleTaskClick = (taskId: Task['id']): void => {
        openTaskModal(taskId)
    }
    const [clonedItems, setClonedItems] = useState<Items | null>(null)
    const [dropIndicator, setDropIndicator] = useState<{ container: UniqueIdentifier | null; index: number | null }>({
        container: null,
        index: null,
    })
    const sensors = useSensors(
        useSensor(MouseSensor),
        useSensor(TouchSensor),
        useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
    )
    const findContainer = (item: Active | Over): UniqueIdentifier => {
        if (isContainer(item)) {
            return item.id
        }
        return tasks.find((t: Task) => t.id === item.id)?.status as UniqueIdentifier
    }

    const onDragCancel = (): void => {
        if (clonedItems) {
            // Reset items to their original state in case items have been
            // Dragged across containers
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

    useEffect(() => {
        if (!activeTask) {
            setItems(kanbanColumns)
        }
    }, [kanbanColumns, activeTask])

    return (
        <div className="space-y-4">
            <h2 className="text-xl font-semibold">Kanban Board</h2>
            <DndContext
                sensors={sensors}
                collisionDetection={closestCorners}
                // collisionDetection={collisionDetectionStrategy}
                measuring={{ droppable: { strategy: MeasuringStrategy.Always } }}
                onDragStart={({ active }) => {
                    const task = tasks.find((t: Task) => t.id === active.id)
                    if (task) {
                        setActiveTask(task)
                        setClonedItems(items)
                    }
                }}
                onDragOver={({ active, over, delta }) => {
                    if (!over) {
                        return
                    }

                    const activeContainer = findContainer(active)
                    const overContainer = findContainer(over)
                    if (!activeContainer || !overContainer) {
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

                    if (overContainer) {
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
                                moveTask(String(active.id), overContainer as TaskStatus, finalIndex)
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
                                    { ...draggedTask, status: overContainer as TaskStatus },
                                    ...current[overContainer].slice(insertIndex),
                                ],
                            }))

                            moveTask(String(active.id), overContainer as TaskStatus, insertIndex)
                        }
                    }

                    setActiveTask(null)
                    setDropIndicator({ container: null, index: null })
                }}
                onDragCancel={onDragCancel}
            >
                <div className="grid grid-cols-5 gap-4">
                    {containers.map((containerId) => {
                        const isAgentOnly = ![TaskStatus.TODO, TaskStatus.BACKLOG].includes(containerId as TaskStatus)

                        return (
                            <div
                                key={containerId}
                                className={cn('bg-bg-light rounded-lg p-3 relative', isAgentOnly && 'opacity-75')}
                            >
                                {isAgentOnly && (
                                    <div className="absolute inset-0 bg-border/20 rounded-lg flex items-center justify-center pointer-events-none z-10">
                                        <div className="bg-bg-light border border-border rounded-lg px-3 py-2 shadow-lg">
                                            <div className="flex items-center gap-2 text-xs text-muted">
                                                <span className="w-2 h-2 bg-warning rounded-full" />
                                                Agent Only
                                            </div>
                                        </div>
                                    </div>
                                )}
                                <div className="flex justify-between items-center mb-3">
                                    <h3 className="font-medium text-sm">Column Title</h3>
                                    <span className="text-xs text-muted bg-border rounded-full px-2 py-1">
                                        {items[containerId].length}
                                    </span>
                                </div>
                                <DroppableContainer key={containerId} id={containerId}>
                                    <SortableContext
                                        items={items[containerId].map((t) => t.id)}
                                        strategy={verticalListSortingStrategy}
                                    >
                                        {items[containerId].map((task, idx) => (
                                            <React.Fragment key={`row-${task.id}`}>
                                                {dropIndicator.container === containerId &&
                                                    dropIndicator.index === idx && <DropIndicator />}
                                                <SortableItem key={task.id} task={task} onClick={handleTaskClick} />
                                            </React.Fragment>
                                        ))}
                                        {dropIndicator.container === containerId &&
                                            dropIndicator.index === items[containerId].length && <DropIndicator />}
                                    </SortableContext>
                                </DroppableContainer>
                            </div>
                        )
                    })}
                </div>
            </DndContext>
            {selectedTask && <TaskModal task={selectedTask} onClose={closeTaskModal} />}
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
        data: { status: task.status },
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
            className={cn('cursor-grab active:cursor-grabbing', isDragging && 'opacity-50')}
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
