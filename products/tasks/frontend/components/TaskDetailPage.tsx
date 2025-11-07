import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'

import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ORIGIN_PRODUCT_COLORS, ORIGIN_PRODUCT_LABELS } from '../constants'
import { taskDetailLogic } from '../taskDetailLogic'
import { tasksLogic } from '../tasksLogic'
import { Task } from '../types'
import { RepositoryConfig, RepositorySelector } from './RepositorySelector'
import { TaskProgressDisplay } from './TaskProgressDisplay'

interface TaskDetailPageProps {
    task: Task
}

export function TaskDetailPage({ task }: TaskDetailPageProps): JSX.Element {
    const { updateTask, runTask } = useActions(taskDetailLogic)
    const { taskLoading } = useValues(taskDetailLogic)
    const { assignTaskToWorkflow } = useActions(tasksLogic)
    const { allWorkflows } = useValues(tasksLogic)

    const [isEditingRepository, setIsEditingRepository] = useState(false)
    const [repositoryConfig, setRepositoryConfig] = useState<RepositoryConfig>({
        integrationId: task?.github_integration || undefined,
        organization: task?.repository_config?.organization || undefined,
        repository: task?.repository_config?.repository || undefined,
    })
    const [savingRepository, setSavingRepository] = useState(false)
    const [selectedWorkflowId, setSelectedWorkflowId] = useState<string>('')

    const isInBacklog = !task.workflow || !task.current_stage

    const getCurrentStage = (): any => {
        if (task.workflow && task.current_stage) {
            const stage = allWorkflows.flatMap((w) => w.stages || []).find((s) => s.id === task.current_stage)
            return stage
        }
        return null
    }

    const currentStage = getCurrentStage()
    const stageKey = currentStage?.key || 'backlog'

    const formatDate = (dateString: string): string => {
        return new Date(dateString).toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        })
    }

    const handleAssignToWorkflow = (e: React.MouseEvent): void => {
        e.stopPropagation()
        if (selectedWorkflowId) {
            assignTaskToWorkflow(task.id, selectedWorkflowId)
        }
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
        <div className="TaskDetailPage">
            <SceneTitleSection
                name={task.title}
                resourceType={{
                    type: 'task',
                }}
            />
            {/* Navigation and status */}
            <div className="flex items-center gap-2 px-6 mb-4">
                <Link to="/tasks">
                    <IconArrowLeft /> Back to Tasks
                </Link>
                <span className="mx-2">·</span>
                <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium">{stageKey}</span>
                <span
                    className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${
                        ORIGIN_PRODUCT_COLORS[task.origin_product]
                    }`}
                >
                    {ORIGIN_PRODUCT_LABELS[task.origin_product]}
                </span>
            </div>
            <SceneDivider />

            {/* Split view container */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 p-6">
                {/* Left panel - Task details */}
                <div className="space-y-6">
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
                        <div>
                            <span className="font-medium text-default">Position:</span>
                            <div className="text-muted">{task.position}</div>
                        </div>
                    </div>

                    {/* Actions */}
                    <div className="space-y-4">
                        {task.workflow && (
                            <div className="pt-4 border-t border-border">
                                <LemonButton
                                    type="primary"
                                    onClick={() => runTask(task.id)}
                                    loading={taskLoading}
                                    fullWidth
                                >
                                    Run Task
                                </LemonButton>
                            </div>
                        )}
                        {isInBacklog && allWorkflows.length > 0 && (
                            <div className="pt-4 border-t border-border">
                                <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                                    <LemonSelect
                                        value={selectedWorkflowId}
                                        onChange={(value) => setSelectedWorkflowId(value)}
                                        options={[
                                            { value: '', label: 'Select workflow...' },
                                            ...allWorkflows.map((workflow) => ({
                                                value: workflow.id,
                                                label: workflow.name,
                                            })),
                                        ]}
                                        placeholder="Select workflow"
                                        size="small"
                                        className="min-w-32"
                                    />
                                    <LemonButton
                                        size="xsmall"
                                        type="primary"
                                        onClick={handleAssignToWorkflow}
                                        disabled={!selectedWorkflowId}
                                    >
                                        Assign
                                    </LemonButton>
                                </div>
                            </div>
                        )}
                    </div>
                </div>

                {/* Right panel - Agent output */}
                <div className="border-l pl-6 h-full">
                    <div className="h-full">
                        <h3 className="text-sm font-medium text-default mb-4">Agent Output</h3>
                        <div className="h-[calc(100vh-300px)] overflow-hidden">
                            <TaskProgressDisplay task={task} />
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
