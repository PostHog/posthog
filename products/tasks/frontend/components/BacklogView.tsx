import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { tasksLogic } from '../tasksLogic'
import { TaskCard } from './TaskCard'
import { TaskCreateModal } from './TaskCreateModal'
import { TaskSummariesMaxTool } from './TaskSummariesMaxTool'

export function BacklogView(): JSX.Element {
    const { unassignedTasks, assignedTasks, isCreateModalOpen, allWorkflows } = useValues(tasksLogic)
    const { assignTaskToWorkflow, openTaskDetail, openCreateModal, closeCreateModal } = useActions(tasksLogic)

    const totalTasks = unassignedTasks.length + assignedTasks.length

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center">
                <div>
                    <h2 className="text-xl font-semibold">All Tasks</h2>
                </div>
                <div className="flex items-center gap-3">
                    <span className="text-sm text-muted">{totalTasks} tasks</span>
                    <LemonButton type="primary" onClick={openCreateModal}>
                        Create Task
                    </LemonButton>
                </div>
            </div>

            {/* Unassigned Tasks Section */}
            {unassignedTasks.length > 0 && (
                <div className="space-y-3">
                    <h3 className="font-semibold text-muted">Unassigned Tasks ({unassignedTasks.length})</h3>
                    <div className="space-y-2">
                        {unassignedTasks.map((task) => (
                            <TaskCard
                                key={task.id}
                                task={task}
                                onAssignToWorkflow={assignTaskToWorkflow}
                                onClick={openTaskDetail}
                                workflows={allWorkflows}
                            />
                        ))}
                    </div>
                </div>
            )}

            {/* Assigned Tasks Section */}
            {assignedTasks.length > 0 && (
                <div className="space-y-3">
                    <h3 className="font-semibold text-muted">Assigned Tasks ({assignedTasks.length})</h3>
                    <div className="space-y-2">
                        {assignedTasks.map((task) => (
                            <TaskCard
                                key={task.id}
                                task={task}
                                onAssignToWorkflow={assignTaskToWorkflow}
                                onClick={openTaskDetail}
                                workflows={allWorkflows}
                            />
                        ))}
                    </div>
                </div>
            )}

            {totalTasks === 0 && (
                <div className="text-center py-8 text-muted">
                    <span>No tasks created yet. Create a task to get started.</span>
                    <TaskSummariesMaxTool />
                </div>
            )}

            <TaskCreateModal isOpen={isCreateModalOpen} onClose={closeCreateModal} />
        </div>
    )
}
