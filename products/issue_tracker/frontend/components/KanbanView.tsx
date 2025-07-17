import { useState } from 'react'
import { useValues, useActions } from 'kea'
import { DragDropContext, Droppable, Draggable, DropResult } from 'react-beautiful-dnd'
import { issueTrackerLogic } from '../IssueTrackerLogic'
import { IssueCard } from './IssueCard'
import { IssueModal } from './IssueModal'
import { IssueStatus } from '../types'

export function KanbanView(): JSX.Element {
    const { kanbanColumns, selectedIssue } = useValues(issueTrackerLogic)
    const { moveIssue, reorderIssues, openIssueModal, closeIssueModal } = useActions(issueTrackerLogic)

    const [isDragging, setIsDragging] = useState(false)

    const handleDragStart = (): void => {
        setIsDragging(true)
    }

    const handleDragEnd = (result: DropResult): void => {
        setIsDragging(false)

        const { destination, source, draggableId } = result

        if (!destination) {
            return
        }

        if (destination.droppableId === source.droppableId && destination.index === source.index) {
            return
        }

        const destinationStatus = destination.droppableId as IssueStatus
        const sourceStatus = source.droppableId as IssueStatus

        // Only allow dropping in TODO and BACKLOG columns
        if (destinationStatus !== IssueStatus.TODO && destinationStatus !== IssueStatus.BACKLOG) {
            return
        }

        // If moving within the same column, just reorder
        if (destinationStatus === sourceStatus) {
            reorderIssues(source.index, destination.index, sourceStatus)
        } else {
            // Moving between columns
            moveIssue(draggableId, destinationStatus, destination.index)
        }
    }

    const handleIssueClick = (issueId: string): void => {
        if (!isDragging) {
            openIssueModal(issueId)
        }
    }

    return (
        <div className="space-y-4">
            <h2 className="text-xl font-semibold">Kanban Board</h2>

            <DragDropContext onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
                <div className="grid grid-cols-5 gap-4">
                    {kanbanColumns.map((column) => {
                        const isAgentOnly = column.id !== IssueStatus.TODO && column.id !== IssueStatus.BACKLOG
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
                                        {column.issues.length}
                                    </span>
                                </div>

                                <Droppable
                                    droppableId={column.id}
                                    isDropDisabled={column.id !== IssueStatus.TODO && column.id !== IssueStatus.BACKLOG}
                                >
                                    {(provided, snapshot) => (
                                        <div
                                            {...provided.droppableProps}
                                            ref={provided.innerRef}
                                            className={`space-y-2 min-h-[200px] ${
                                                snapshot.isDraggingOver &&
                                                (column.id === IssueStatus.TODO || column.id === IssueStatus.BACKLOG)
                                                    ? 'bg-accent-light rounded'
                                                    : snapshot.isDraggingOver
                                                    ? 'bg-danger-light rounded'
                                                    : ''
                                            }`}
                                        >
                                            {column.issues.map((issue, index) => (
                                                <Draggable key={issue.id} draggableId={issue.id} index={index}>
                                                    {(provided, snapshot) => (
                                                        <div
                                                            ref={provided.innerRef}
                                                            {...provided.draggableProps}
                                                            {...provided.dragHandleProps}
                                                            className={`${
                                                                snapshot.isDragging ? 'rotate-3 shadow-lg' : ''
                                                            }`}
                                                        >
                                                            <IssueCard
                                                                issue={issue}
                                                                draggable
                                                                onClick={handleIssueClick}
                                                            />
                                                        </div>
                                                    )}
                                                </Draggable>
                                            ))}
                                            {provided.placeholder}
                                        </div>
                                    )}
                                </Droppable>
                            </div>
                        )
                    })}
                </div>
            </DragDropContext>

            <IssueModal issue={selectedIssue} isOpen={!!selectedIssue} onClose={closeIssueModal} />
        </div>
    )
}
