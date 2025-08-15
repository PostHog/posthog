import { useValues, useActions } from 'kea'
import { LemonButton } from '@posthog/lemon-ui'
import { taskTrackerLogic } from '../TaskTrackerLogic'
import { TaskCard } from './TaskCard'
import { TaskModal } from './TaskModal'
import { TaskCreateModal } from './TaskCreateModal'
import { userLogic } from 'scenes/userLogic'

export function BacklogView(): JSX.Element {
    const { backlogTasks, selectedTask, isCreateModalOpen } = useValues(taskTrackerLogic)
    const { scopeTask, openTaskModal, closeTaskModal, openCreateModal, closeCreateModal } = useActions(taskTrackerLogic)
    const { user } = useValues(userLogic)

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                <h2 className="text-xl font-semibold">Backlog</h2>
                <div className="flex items-center gap-3">
                    <span className="text-sm text-muted">{backlogTasks.length} tasks</span>
                    <LemonButton type="primary" onClick={openCreateModal}>
                        Create Task
                    </LemonButton>
                </div>
            </div>

            <div className="space-y-2">
                {backlogTasks.map((task) => (
                    <TaskCard key={task.id} task={task} onScope={scopeTask} onClick={openTaskModal} />
                ))}
            </div>

            {backlogTasks.length === 0 && <div className="text-center py-8 text-muted">No tasks in backlog</div>}

            <TaskModal task={selectedTask} isOpen={!!selectedTask} onClose={closeTaskModal} />
            <TaskCreateModal 
                isOpen={isCreateModalOpen} 
                onClose={closeCreateModal} 
                teamId={user?.team?.id || 0} 
            />
        </div>
    )
}
