import { LemonModal, LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { Task, TaskStatus } from '../types'
import { taskTrackerLogic } from '../TaskTrackerLogic'
import { STATUS_LABELS, STATUS_COLORS, ORIGIN_PRODUCT_LABELS, ORIGIN_PRODUCT_COLORS } from '../constants'
import { TaskProgressDisplay } from './TaskProgressDisplay'

interface TaskModalProps {
    task: Task | null
    isOpen: boolean
    onClose: () => void
}

export function TaskModal({ task, isOpen, onClose }: TaskModalProps): JSX.Element {
    const { scopeTask } = useActions(taskTrackerLogic)

    if (!task) {
        return <></>
    }

    const formatDate = (dateString: string): string => {
        return new Date(dateString).toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        })
    }

    const handleScope = (): void => {
        scopeTask(task.id)
        onClose()
    }

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title={task.title} width={600}>
            <div className="space-y-6">
                {/* Header with status and origin */}
                <div className="flex justify-between items-start">
                    <div className="flex gap-2">
                        <span
                            className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${
                                STATUS_COLORS[task.status]
                            }`}
                        >
                            {STATUS_LABELS[task.status]}
                        </span>
                        <span
                            className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${
                                ORIGIN_PRODUCT_COLORS[task.origin_product]
                            }`}
                        >
                            {ORIGIN_PRODUCT_LABELS[task.origin_product]}
                        </span>
                    </div>
                    <span className="text-xs text-muted">Position: {task.position}</span>
                </div>

                {/* Title */}
                <div>
                    <h2 className="text-xl font-semibold text-default mb-2">{task.title}</h2>
                </div>

                {/* Description */}
                <div>
                    <h3 className="text-sm font-medium text-default mb-2">Description</h3>
                    <p className="text-sm text-muted leading-relaxed">{task.description}</p>
                </div>

                {/* Repository Configuration */}
                {task.repository_scope && (
                    <div>
                        <h3 className="text-sm font-medium text-default mb-2">Repository Configuration</h3>
                        <div className="bg-bg-light p-3 rounded border">
                            <div className="space-y-2">
                                <div className="flex items-center gap-2">
                                    <span className="text-xs font-medium text-muted">Scope:</span>
                                    <span className="text-sm capitalize">{task.repository_scope.replace('_', ' ')}</span>
                                </div>
                                
                                {task.repository_scope === 'single' && task.primary_repository && (
                                    <div className="flex items-center gap-2">
                                        <span className="text-xs font-medium text-muted">Repository:</span>
                                        <span className="text-sm font-mono text-primary">
                                            {task.primary_repository.organization}/{task.primary_repository.repository}
                                        </span>
                                    </div>
                                )}
                                
                                {task.repository_scope === 'multiple' && task.repository_list && (
                                    <div>
                                        <span className="text-xs font-medium text-muted">Repositories ({task.repository_list.length}):</span>
                                        <div className="mt-1 space-y-1">
                                            {task.repository_list.map((repo, index) => (
                                                <div key={index} className="text-sm font-mono text-primary">
                                                    {repo.organization}/{repo.repository}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                                
                                {task.repository_scope === 'smart_select' && (
                                    <div className="flex items-center gap-2">
                                        <span className="text-xs font-medium text-muted">Mode:</span>
                                        <span className="text-sm">AI will select repositories based on task context</span>
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                )}

                {/* Progress Display - only show for in_progress, testing, or done tasks */}
                {[TaskStatus.IN_PROGRESS, TaskStatus.TESTING, TaskStatus.DONE].includes(task.status) && (
                    <TaskProgressDisplay task={task} />
                )}

                {/* Metadata */}
                <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                        <span className="font-medium text-default">Created:</span>
                        <div className="text-muted">{formatDate(task.created_at)}</div>
                    </div>
                    <div>
                        <span className="font-medium text-default">Last Updated:</span>
                        <div className="text-muted">{formatDate(task.updated_at)}</div>
                    </div>
                </div>

                {/* Actions */}
                <div className="flex justify-between items-center pt-4 border-t border-border">
                    <div>
                        {task.status === TaskStatus.BACKLOG && (
                            <LemonButton type="primary" onClick={handleScope}>
                                Scope to Todo
                            </LemonButton>
                        )}
                    </div>
                    <LemonButton onClick={onClose}>Close</LemonButton>
                </div>
            </div>
        </LemonModal>
    )
}
