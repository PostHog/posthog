import { useState } from 'react'
import { useValues, useActions } from 'kea'
import { taskTrackerLogic } from '../TaskTrackerLogic'
import { TaskCard } from './TaskCard'
import { TaskModal } from './TaskModal'
import { Task, TaskStatus } from '../types'
import { DndContext, useDraggable, useDroppable } from '@dnd-kit/core'
import { PropsWithChildren } from 'react'

export function KanbanView(): JSX.Element {
    const { kanbanColumns, selectedTask } = useValues(taskTrackerLogic)
    const { openTaskModal, closeTaskModal } = useActions(taskTrackerLogic)

    const [isDragging, setIsDragging] = useState(false)

    const handleDragStart = (): void => {
        setIsDragging(true)
    }

    const handleDragEnd = (): void => {
        setIsDragging(false)

        // const { destination, source, draggableId } = result

        // if (!destination) {
        //     return
        // }

        // if (destination.droppableId === source.droppableId && destination.index === source.index) {
        //     return
        // }

        // const destinationStatus = destination.droppableId as TaskStatus
        // const sourceStatus = source.droppableId as TaskStatus

        // // Only allow dropping in TODO and BACKLOG columns
        // if (destinationStatus !== TaskStatus.TODO && destinationStatus !== TaskStatus.BACKLOG) {
        //     return
        // }

        // // If moving within the same column, just reorder
        // if (destinationStatus === sourceStatus) {
        //     reorderTasks(source.index, destination.index, sourceStatus)
        // } else {
        //     // Moving between columns
        //     moveTask(draggableId, destinationStatus, destination.index)
        // }
    }

    const handleTaskClick = (taskId: Task['id']): void => {
        if (!isDragging) {
            openTaskModal(taskId)
        }
    }

    return (
        <div className="space-y-4">
            <h2 className="text-xl font-semibold">Kanban Board</h2>

            <DndContext onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
                <div className="grid grid-cols-5 gap-4">
                    {kanbanColumns.map((column) => {
                        const isAgentOnly = column.id !== TaskStatus.TODO && column.id !== TaskStatus.BACKLOG
                        return (
                            <div
                                key={column.id}
                                className={`bg-bg-light rounded-lg p-3 relative ${isAgentOnly ? 'opacity-75' : ''}`}
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

                                <Droppable
                                    id={column.id}
                                    disabled={column.id !== TaskStatus.TODO && column.id !== TaskStatus.BACKLOG}
                                >
                                    {column.tasks.map((task) => (
                                        <Draggable key={task.id} task={task} onClick={handleTaskClick} />
                                    ))}
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
    disabled,
    children,
}: PropsWithChildren<{ id: TaskStatus; disabled: boolean }>): JSX.Element => {
    const { setNodeRef, isOver } = useDroppable({ id, disabled })
    return (
        <div
            ref={setNodeRef}
            className={`space-y-2 min-h-[200px] ${
                isOver && (id === TaskStatus.TODO || id === TaskStatus.BACKLOG)
                    ? 'bg-accent-light rounded'
                    : isOver
                      ? 'bg-danger-light rounded'
                      : ''
            }`}
        >
            {children}
        </div>
    )
}

const Draggable = ({ task, onClick }: { task: Task; onClick: (id: Task['id']) => void }): JSX.Element => {
    const { setNodeRef, isDragging } = useDraggable({ id: task.id })

    return (
        <div ref={setNodeRef} className={isDragging ? 'rotate-3 shadow-lg' : ''}>
            <TaskCard task={task} draggable onClick={() => onClick(task.id)} />
        </div>
    )
}
