import {
    Active,
    DndContext,
    DragOverlay,
    MeasuringStrategy,
    MouseSensor,
    Over,
    TouchSensor,
    UniqueIdentifier,
    useDroppable,
    useSensor,
    useSensors,
} from '@dnd-kit/core'
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import React, { PropsWithChildren, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { cn } from 'lib/utils/css-classes'

import { taskTrackerLogic } from './../taskTrackerLogic'
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
    const { setNodeRef } = useDroppable({ id, data: { type: 'container' } })

    return (
        <div ref={disabled ? undefined : setNodeRef} className="space-y-2 min-h-[200px]">
            {children}
        </div>
    )
}

type Items = Record<UniqueIdentifier, Task[]>

export function KanbanView(): JSX.Element {
    const { tasks, kanbanColumns, selectedTask } = useValues(taskTrackerLogic)
    const { openTaskModal, closeTaskModal } = useActions(taskTrackerLogic)

    const [items, setItems] = useState<Items>(kanbanColumns)
    const [activeTask, setActiveTask] = useState<Task | null>(null)
    // const lastOverId = useRef<UniqueIdentifier | null>(null)
    const recentlyMovedToNewContainer = useRef(false)

    const containers = Object.keys(kanbanColumns) as UniqueIdentifier[]

    const handleTaskClick = (taskId: Task['id']): void => {
        openTaskModal(taskId)
    }

    /**
     * Custom collision detection strategy optimized for multiple containers
     *
     * - First, find any droppable containers intersecting with the pointer.
     * - If there are none, find intersecting containers with the active draggable.
     * - If there are no intersecting containers, return the last matched intersection
     *
     */
    // const collisionDetectionStrategy: CollisionDetection = useCallback(
    //     (args) => {
    //         if (activeId && activeId in items) {
    //             return closestCenter({
    //                 ...args,
    //                 droppableContainers: args.droppableContainers.filter((container) => container.id in items),
    //             })
    //         }

    //         // Start by finding any intersecting droppable
    //         const pointerIntersections = pointerWithin(args)
    //         const intersections =
    //             pointerIntersections.length > 0
    //                 ? // If there are droppables intersecting with the pointer, return those
    //                   pointerIntersections
    //                 : rectIntersection(args)
    //         let overId = getFirstCollision(intersections, 'id')

    //         if (overId != null) {
    //             if (overId in items) {
    //                 const containerItems = items[overId]

    //                 // If a container is matched and it contains items (columns 'A', 'B', 'C')
    //                 if (containerItems.length > 0) {
    //                     // Return the closest droppable within that container
    //                     overId = closestCenter({
    //                         ...args,
    //                         droppableContainers: args.droppableContainers.filter(
    //                             (container) => container.id !== overId && containerItems.includes(container.id)
    //                         ),
    //                     })[0]?.id
    //                 }
    //             }

    //             lastOverId.current = overId

    //             return [{ id: overId }]
    //         }

    //         // When a draggable item moves to a new container, the layout may shift
    //         // and the `overId` may become `null`. We manually set the cached `lastOverId`
    //         // to the id of the draggable item that was moved to the new container, otherwise
    //         // the previous `overId` will be returned which can cause items to incorrectly shift positions
    //         if (recentlyMovedToNewContainer.current) {
    //             lastOverId.current = activeId
    //         }

    //         // If no droppable is matched, return the last match
    //         return lastOverId.current ? [{ id: lastOverId.current }] : []
    //     },
    //     [activeId, items]
    // )
    const [clonedItems, setClonedItems] = useState<Items | null>(null)
    const sensors = useSensors(useSensor(MouseSensor), useSensor(TouchSensor))
    const findContainer = (item: Active | Over): UniqueIdentifier => {
        if (isContainer(item)) {
            return item.id
        }
        return tasks.find((t) => t.id === item.id)?.status as UniqueIdentifier
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

    return (
        <div className="space-y-4">
            <h2 className="text-xl font-semibold">Kanban Board</h2>
            <DndContext
                sensors={sensors}
                // collisionDetection={collisionDetectionStrategy}
                measuring={{ droppable: { strategy: MeasuringStrategy.Always } }}
                onDragStart={({ active }) => {
                    const task = tasks.find((t) => t.id === active.id)
                    if (task) {
                        setActiveTask(task)
                        setClonedItems(items)
                    }
                }}
                onDragOver={({ active, over }) => {
                    if (!over) {
                        return
                    }

                    const activeContainer = findContainer(active)
                    const overContainer = findContainer(over)

                    if (!activeContainer || !overContainer) {
                        return
                    }

                    if (activeContainer !== overContainer) {
                        setItems((items) => {
                            const activeItems = items[activeContainer]
                            const overItems = items[overContainer]
                            const overIndex = overItems.findIndex((item) => item.id === over.id)
                            const activeIndex = activeItems.findIndex((item) => item.id === active.id)

                            let newIndex: number

                            if (over.id in items) {
                                newIndex = overItems.length + 1
                            } else {
                                const isBelowOverItem =
                                    over &&
                                    active.rect.current.translated &&
                                    active.rect.current.translated.top > over.rect.top + over.rect.height

                                const modifier = isBelowOverItem ? 1 : 0

                                newIndex = overIndex >= 0 ? overIndex + modifier : overItems.length + 1
                            }

                            recentlyMovedToNewContainer.current = true

                            return {
                                ...items,
                                [activeContainer]: items[activeContainer].filter((item) => item.id !== active.id),
                                [overContainer]: [
                                    ...items[overContainer].slice(0, newIndex),
                                    items[activeContainer][activeIndex],
                                    ...items[overContainer].slice(newIndex, items[overContainer].length),
                                ],
                            }
                        })
                    }
                }}
                onDragEnd={({ active, over }) => {
                    const activeContainer = findContainer(active)

                    if (!activeContainer) {
                        setActiveTask(null)
                        return
                    }

                    if (over == null) {
                        setActiveTask(null)
                        return
                    }

                    const overContainer = findContainer(over)

                    if (overContainer) {
                        const activeIndex = items[activeContainer].findIndex((t) => t.id === active.id)
                        const overIndex = items[overContainer].findIndex((t) => t.id === over.id)

                        if (activeIndex !== overIndex) {
                            setItems((items) => ({
                                ...items,
                                [overContainer]: arrayMove(items[overContainer], activeIndex, overIndex),
                            }))
                        }
                    }

                    setActiveTask(null)
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
                                    <SortableContext items={items[containerId]} strategy={verticalListSortingStrategy}>
                                        {items[containerId].map((task) => {
                                            return <SortableItem key={task.id} task={task} onClick={handleTaskClick} />
                                        })}
                                    </SortableContext>
                                </DroppableContainer>
                            </div>
                        )
                    })}
                </div>
                {createPortal(
                    <DragOverlay>{activeTask ? renderSortableItemDragOverlay(activeTask) : null}</DragOverlay>,
                    document.body
                )}
            </DndContext>
            <TaskModal task={selectedTask} isOpen={!!selectedTask} onClose={closeTaskModal} />
        </div>
    )

    function renderSortableItemDragOverlay(task: Task): React.ReactElement {
        return (
            <div className="rotate-3 shadow-lg z-10">
                <TaskCard task={task} draggable />
            </div>
        )
    }
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
            className={cn(isDragging && 'opacity-50')}
        >
            <TaskCard task={task} draggable onClick={() => onClick(task.id)} />
        </div>
    )
}

function isContainer(item: Active | Over): boolean {
    return item.data.current && item.data.current.type === 'container' ? true : false
}
