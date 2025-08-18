import {
    DndContext,
    DragStartEvent,
    MouseSensor,
    UniqueIdentifier,
    useDroppable,
    useSensor,
    useSensors,
} from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import { useState } from 'react'
import { PropsWithChildren } from 'react'

import { cn } from 'lib/utils/css-classes'

import { taskTrackerLogic } from '../taskTrackerLogic'
import { Task, TaskStatus } from '../types'
import { TaskCard } from './TaskCard'
import { TaskModal } from './TaskModal'

export function KanbanView(): JSX.Element {
    const { tasks, kanbanColumns, selectedTask } = useValues(taskTrackerLogic)
    const { openTaskModal, closeTaskModal } = useActions(taskTrackerLogic)

    const sensors = useSensors(useSensor(MouseSensor))
    const [draggingId, setDraggingId] = useState<UniqueIdentifier | null>(null)
    // const [clonedItems, setClonedItems] = useState<Task[] | null>(null)

    const onDragStart = ({ active }: DragStartEvent): void => {
        setDraggingId(active.id)
        // setClonedItems(tasks)
    }

    const isDragging = !!draggingId

    const onDragEnd = (): void => {
        // if (active.id in items && over?.id) {
        //   setContainers((containers) => {
        //     const activeIndex = containers.indexOf(active.id);
        //     const overIndex = containers.indexOf(over.id);
        //     return arrayMove(containers, activeIndex, overIndex);
        //   });
        // }
        // const activeContainer = findContainer(active.id);
        // if (!activeContainer) {
        //   setActiveId(null);
        //   return;
        // }
        // const overId = over?.id;
        // if (overId == null) {
        //   setActiveId(null);
        //   return;
        // }
        // if (overId === TRASH_ID) {
        //   setItems((items) => ({
        //     ...items,
        //     [activeContainer]: items[activeContainer].filter(
        //       (id) => id !== activeId
        //     ),
        //   }));
        //   setActiveId(null);
        //   return;
        // }
        // const overContainer = findContainer(overId);
        // if (overContainer) {
        //   const activeIndex = items[activeContainer].indexOf(active.id);
        //   const overIndex = items[overContainer].indexOf(overId);
        //   if (activeIndex !== overIndex) {
        //     setItems((items) => ({
        //       ...items,
        //       [overContainer]: arrayMove(
        //         items[overContainer],
        //         activeIndex,
        //         overIndex
        //       ),
        //     }));
        //   }
        // }
        // setActiveId(null);
    }

    // const onDragEnd = (): void => {
    //     setIsDragging(false)

    //     // const { destination, source, draggableId } = result

    //     // if (!destination) {
    //     //     return
    //     // }

    //     // if (destination.droppableId === source.droppableId && destination.index === source.index) {
    //     //     return
    //     // }

    //     // const destinationStatus = destination.droppableId as TaskStatus
    //     // const sourceStatus = source.droppableId as TaskStatus

    //     // // Only allow dropping in TODO and BACKLOG columns
    //     // if (destinationStatus !== TaskStatus.TODO && destinationStatus !== TaskStatus.BACKLOG) {
    //     //     return
    //     // }

    //     // // If moving within the same column, just reorder
    //     // if (destinationStatus === sourceStatus) {
    //     //     reorderTasks(source.index, destination.index, sourceStatus)
    //     // } else {
    //     //     // Moving between columns
    //     //     moveTask(draggableId, destinationStatus, destination.index)
    //     // }
    // }

    const handleTaskClick = (taskId: Task['id']): void => {
        if (!isDragging) {
            openTaskModal(taskId)
        }
    }

    return (
        <div className="space-y-4">
            <h2 className="text-xl font-semibold">Kanban Board</h2>

            <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd}>
                <div className="grid grid-cols-5 gap-4">
                    {kanbanColumns.map((column) => {
                        const isAgentOnly = column.id !== TaskStatus.TODO && column.id !== TaskStatus.BACKLOG

                        const columnTasks = tasks.filter((t) => column.id === t.status)

                        return (
                            <div
                                key={column.id}
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
                                    <h3 className="font-medium text-sm">{column.title}</h3>
                                    <span className="text-xs text-muted bg-border rounded-full px-2 py-1">
                                        {column.tasks.length}
                                    </span>
                                </div>
                                <Droppable id={column.id} isAgentOnly={isAgentOnly}>
                                    <SortableContext items={columnTasks} strategy={verticalListSortingStrategy}>
                                        {columnTasks.map((task) => (
                                            <Draggable key={task.id} task={task} onClick={handleTaskClick} />
                                        ))}
                                    </SortableContext>
                                </Droppable>
                            </div>
                        )
                    })}
                </div>
            </DndContext>

            <TaskModal task={selectedTask} isOpen={!!selectedTask} onClose={closeTaskModal} />
        </div>
    )
}

const Droppable = ({
    id,
    isAgentOnly,
    children,
}: PropsWithChildren<{ id: TaskStatus; isAgentOnly: boolean; className?: string }>): JSX.Element => {
    const { setNodeRef } = useDroppable({ id, disabled: isAgentOnly })

    return (
        <div ref={setNodeRef} className={cn('space-y-2 min-h-[200px]')}>
            {children}
        </div>
    )
}

const Draggable = ({ task, onClick }: { task: Task; onClick: (id: Task['id']) => void }): JSX.Element => {
    const { setNodeRef, listeners, attributes, isDragging, transform, transition } = useSortable({
        id: task.id,
    })

    return (
        <div
            ref={setNodeRef}
            {...attributes}
            {...listeners}
            style={{ transform: CSS.Translate.toString(transform), transition }}
            className={isDragging ? 'rotate-3 shadow-lg' : ''}
        >
            <TaskCard task={task} draggable onClick={() => onClick(task.id)} />
        </div>
    )
}
