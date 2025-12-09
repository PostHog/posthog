import { useActions, useValues } from 'kea'

import { IconExternal, IconGithub, IconPlay, IconTrash } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { taskDetailSceneLogic } from '../logics/taskDetailSceneLogic'
import { TaskRunItem } from './TaskRunItem'
import { TaskRunStatusBadge } from './TaskRunStatusBadge'
import { TaskSessionView } from './TaskSessionView'

export interface TaskDetailPageProps {
    taskId: string
}

export function TaskDetailPage({ taskId }: TaskDetailPageProps): JSX.Element {
    const sceneLogic = taskDetailSceneLogic({ taskId })
    const { task, taskLoading, runs, selectedRunId, selectedRun, runsLoading, logs, logsLoading, shouldPollLogs } =
        useValues(sceneLogic)
    const { setSelectedRunId, runTask, deleteTask, updateTask } = useActions(sceneLogic)

    if (!task) {
        return <div className="text-center py-8 text-muted">Task not found</div>
    }

    const hasBeenRun = runs.length > 0
    const canEdit = !hasBeenRun

    const latestRun = runs.length > 0 ? runs[0] : null
    const isLatestRunCompleted = latestRun?.status === 'completed'
    const runButtonText = !hasBeenRun ? 'Run task' : isLatestRunCompleted ? 'Run again' : 'Retry task'

    const prUrl = selectedRun?.output?.pr_url as string | undefined

    return (
        <SceneContent>
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

                {runs.length >= 1 && (
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
                onNameChange={(value) => updateTask({ data: { title: value } })}
                onDescriptionChange={(value) => updateTask({ data: { description: value } })}
                canEdit={canEdit}
                renameDebounceMs={500}
                saveOnBlur={true}
                actions={
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconExternal />}
                            onClick={() => window.open(`posthog-array://task/${task.id}`, '_blank')}
                        >
                            Open in Array
                        </LemonButton>
                        {prUrl && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconGithub />}
                                onClick={() => window.open(prUrl, '_blank')}
                            >
                                View PR
                            </LemonButton>
                        )}
                        <LemonButton type="primary" size="small" icon={<IconPlay />} onClick={runTask}>
                            {runButtonText}
                        </LemonButton>
                    </div>
                }
            />

            {selectedRun && (
                <div className="flex items-center gap-3 px-4 py-2 border-b">
                    <TaskRunStatusBadge run={selectedRun} />
                    <span className="text-sm text-muted">
                        Started {dayjs(selectedRun.created_at).format('MMM D, YYYY HH:mm')}
                    </span>
                    {selectedRun.branch && <code className="text-xs text-muted">{selectedRun.branch}</code>}
                </div>
            )}

            {runsLoading ? (
                <div className="flex items-center justify-center h-32">
                    <Spinner />
                </div>
            ) : runs.length === 0 ? (
                <div className="text-center py-16">
                    <p className="text-muted">This task hasn't been run yet</p>
                </div>
            ) : selectedRun ? (
                <div className="flex-1 overflow-hidden">
                    <TaskSessionView logs={logs} loading={logsLoading} isPolling={shouldPollLogs} />
                </div>
            ) : null}
        </SceneContent>
    )
}
