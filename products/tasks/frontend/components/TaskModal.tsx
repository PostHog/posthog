import { LemonModal, LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { useState } from 'react'
import { Task, TaskStatus } from '../types'
import { taskTrackerLogic } from '../TaskTrackerLogic'
import { STATUS_LABELS, STATUS_COLORS, ORIGIN_PRODUCT_LABELS, ORIGIN_PRODUCT_COLORS } from '../constants'
import { TaskProgressDisplay } from './TaskProgressDisplay'
import { RepositorySelector, RepositoryConfig } from './RepositorySelector'
import api from 'lib/api'

interface TaskModalProps {
    task: Task | null
    isOpen: boolean
    onClose: () => void
}

export function TaskModal({ task, isOpen, onClose }: TaskModalProps): JSX.Element {
    const { scopeTask, updateTask } = useActions(taskTrackerLogic)
    const [isEditingRepository, setIsEditingRepository] = useState(false)
    const [repositoryConfig, setRepositoryConfig] = useState<RepositoryConfig>({
        integrationId: task?.github_integration || undefined,
        organization: task?.repository_config?.organization || undefined,
        repository: task?.repository_config?.repository || undefined,
    })
    const [savingRepository, setSavingRepository] = useState(false)

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

    const handleSaveRepository = async (): Promise<void> => {
        if (!repositoryConfig.integrationId || !repositoryConfig.organization || !repositoryConfig.repository) {
            return
        }

        setSavingRepository(true)
        try {
            const updateData = {
                github_integration: repositoryConfig.integrationId,
                repository_config: {
                    organization: repositoryConfig.organization,
                    repository: repositoryConfig.repository,
                },
            }

            await api.tasks.update(task.id, updateData)
            updateTask(task.id, updateData)
            setIsEditingRepository(false)
        } catch (error) {
            console.error('Failed to update repository:', error)
        } finally {
            setSavingRepository(false)
        }
    }

    const handleCancelEdit = (): void => {
        setRepositoryConfig({
            integrationId: task?.github_integration || undefined,
            organization: task?.repository_config?.organization || undefined,
            repository: task?.repository_config?.repository || undefined,
        })
        setIsEditingRepository(false)
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
                <div>
                    <div className="flex items-center justify-between mb-2">
                        <h3 className="text-sm font-medium text-default">Repository Configuration</h3>
                        {!isEditingRepository && (
                            <LemonButton size="small" type="secondary" onClick={() => setIsEditingRepository(true)}>
                                Edit
                            </LemonButton>
                        )}
                    </div>

                    {isEditingRepository ? (
                        <div className="space-y-4">
                            <RepositorySelector value={repositoryConfig} onChange={setRepositoryConfig} />
                            <div className="flex gap-2">
                                <LemonButton
                                    type="primary"
                                    size="small"
                                    onClick={handleSaveRepository}
                                    loading={savingRepository}
                                    disabled={
                                        !repositoryConfig.integrationId ||
                                        !repositoryConfig.organization ||
                                        !repositoryConfig.repository
                                    }
                                >
                                    Save
                                </LemonButton>
                                <LemonButton type="secondary" size="small" onClick={handleCancelEdit}>
                                    Cancel
                                </LemonButton>
                            </div>
                        </div>
                    ) : (
                        <div className="bg-bg-light p-3 rounded border">
                            {task.repository_config?.organization && task.repository_config?.repository ? (
                                <div className="flex items-center gap-2">
                                    <span className="text-xs font-medium text-muted">Repository:</span>
                                    <span className="text-sm font-mono text-primary">
                                        {task.repository_config.organization}/{task.repository_config.repository}
                                    </span>
                                </div>
                            ) : (
                                <div className="text-sm text-muted italic">
                                    No repository configured - click Edit to add one
                                </div>
                            )}
                        </div>
                    )}
                </div>

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
