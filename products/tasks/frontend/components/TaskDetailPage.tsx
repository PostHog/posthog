import { useActions, useValues } from 'kea'

import { IconPlay, IconTrash } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { taskDetailLogic } from '../taskDetailLogic'
import { TaskRunItem } from './TaskRunItem'
import { TaskRunLogs } from './TaskRunLogs'

export interface TaskDetailPageProps {
    taskId: string
}

export function TaskDetailPage({ taskId }: TaskDetailPageProps): JSX.Element {
    const logic = taskDetailLogic({ taskId })
    const { task, taskLoading, runs, runsLoading, selectedRunId, logs, logsLoading } = useValues(logic)
    const { setSelectedRunId, runTask, deleteTask, updateTask } = useActions(logic)

    if (taskLoading) {
        return (
            <div className="flex items-center justify-center h-64">
                <Spinner />
            </div>
        )
    }

    if (!task) {
        return <div className="text-center py-8 text-muted">Task not found</div>
    }

    const hasBeenRun = runs.length > 0
    const canEdit = !hasBeenRun

    const latestRun = runs.length > 0 ? runs[0] : null
    const isLatestRunCompleted = latestRun?.status === 'completed'
    const runButtonText = !hasBeenRun ? 'Run task' : isLatestRunCompleted ? 'Run again' : 'Retry task'

    return (
        <SceneContent>
            <div className="flex items-center gap-2 mb-2">
                <SceneBreadcrumbBackButton />
            </div>

            <ScenePanel>
                <ScenePanelInfoSection>
                    <div className="flex flex-col gap-3">
                        <div>
                            <div className="text-xs text-muted mb-1">Task ID</div>
                            <div className="font-mono text-sm">{task.slug}</div>
                        </div>
                        <div>
                            <div className="text-xs text-muted mb-1">Repository</div>
                            <div className="text-sm">{task.repository}</div>
                        </div>
                        <div>
                            <div className="text-xs text-muted mb-1">Created by</div>
                            <div className="text-sm">
                                {task.created_by?.first_name || task.created_by?.email || 'Unknown'}
                            </div>
                        </div>
                        <div>
                            <div className="text-xs text-muted mb-1">Created</div>
                            <div className="text-sm">{dayjs(task.created_at).format('MMM D, YYYY HH:mm')}</div>
                        </div>
                    </div>
                </ScenePanelInfoSection>

                <ScenePanelDivider />

                <ScenePanelActionsSection>
                    <ButtonPrimitive menuItem variant="danger" onClick={deleteTask}>
                        <IconTrash />
                        Delete task
                    </ButtonPrimitive>
                </ScenePanelActionsSection>

                {runs.length > 1 && (
                    <>
                        <ScenePanelDivider />
                        <ScenePanelInfoSection>
                            <div className="text-xs font-semibold text-muted mb-2">Run History</div>
                            <div className="flex flex-col gap-1">
                                {runs.map((run) => (
                                    <TaskRunItem
                                        key={run.id}
                                        run={run}
                                        isSelected={run.id === selectedRunId}
                                        onClick={() => setSelectedRunId(run.id)}
                                    />
                                ))}
                            </div>
                        </ScenePanelInfoSection>
                    </>
                )}
            </ScenePanel>

            <SceneTitleSection
                name={task?.title}
                description={task?.description}
                resourceType={{ type: 'task' }}
                isLoading={taskLoading}
                onNameChange={(value) => updateTask({ title: value })}
                onDescriptionChange={(value) => updateTask({ description: value })}
                canEdit={canEdit}
                renameDebounceMs={500}
                saveOnBlur={true}
                actions={
                    <LemonButton type="primary" size="small" icon={<IconPlay />} onClick={runTask}>
                        {runButtonText}
                    </LemonButton>
                }
            />

            {runsLoading ? (
                <div className="flex items-center justify-center h-32">
                    <Spinner />
                </div>
            ) : runs.length === 0 ? (
                <div className="text-center py-16">
                    <p className="text-muted">This task hasn't been run yet</p>
                </div>
            ) : (
                <div className="px-4">
                    <TaskRunLogs logs={logs} loading={logsLoading} />
                </div>
            )}
        </SceneContent>
    )
}
