import { useActions, useValues } from 'kea'

import { IconGithub, IconPlay, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSelect, LemonTabs, Spinner } from '@posthog/lemon-ui'

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

import { taskDetailLogic } from '../taskDetailLogic'
import { TaskRun } from '../types'
import { TaskRunLogs } from './TaskRunLogs'
import { TaskStatusBadge } from './TaskStatusBadge'

export interface TaskDetailPageProps {
    taskId: string
}

export function TaskDetailPage({ taskId }: TaskDetailPageProps): JSX.Element {
    const logic = taskDetailLogic({ taskId })
    const { task, taskLoading, runs, runsLoading, selectedRunId, selectedRun, logs, logsLoading } = useValues(logic)
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

    const runOptions = runs.map((run) => ({
        label: formatRunLabel(run),
        value: run.id,
    }))

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
            </ScenePanel>

            <SceneTitleSection
                name={task?.title}
                description={task?.description}
                resourceType={{ type: 'task' }}
                isLoading={taskLoading}
                onNameChange={(value) => updateTask({ title: value })}
                onDescriptionChange={(value) => updateTask({ description: value })}
                canEdit={true}
                renameDebounceMs={500}
                saveOnBlur={true}
                actions={
                    <LemonButton type="primary" size="small" icon={<IconPlay />} onClick={runTask}>
                        Run task
                    </LemonButton>
                }
            />

            <div className="px-4">
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold mb-0">Runs</h2>
                    {runs.length > 0 && (
                        <LemonSelect
                            value={selectedRunId}
                            onChange={(value) => setSelectedRunId(value as string)}
                            options={runOptions}
                            placeholder="Select a run"
                            className="min-w-64"
                        />
                    )}
                </div>

                {runsLoading ? (
                    <div className="flex items-center justify-center h-32">
                        <Spinner />
                    </div>
                ) : runs.length === 0 ? (
                    <div className="text-center py-8 border rounded bg-bg-light">
                        <p className="text-muted mb-2">No runs yet</p>
                        <LemonButton type="primary" icon={<IconPlay />} onClick={runTask}>
                            Run this task
                        </LemonButton>
                    </div>
                ) : selectedRun ? (
                    <div>
                        <div className="flex flex-wrap gap-8 p-4 bg-bg-light rounded">
                            <div className="flex flex-col gap-1">
                                <span className="text-muted">Status:</span>
                                <TaskStatusBadge task={{ ...task, latest_run: selectedRun }} />
                            </div>
                            {selectedRun.branch && (
                                <div className="flex flex-col gap-1">
                                    <span className="text-muted">Branch:</span>
                                    <span className="font-medium font-mono text-sm">{selectedRun.branch}</span>
                                </div>
                            )}
                            {selectedRun.stage && (
                                <div className="flex flex-col gap-1">
                                    <span className="text-muted">Stage:</span>
                                    <span className="font-medium">{selectedRun.stage}</span>
                                </div>
                            )}
                            <div className="flex flex-col gap-1">
                                <span className="text-muted">Started:</span>
                                <span className="font-medium">
                                    {dayjs(selectedRun.created_at).format('MMM D, YYYY HH:mm:ss')}
                                </span>
                            </div>
                            {selectedRun.completed_at && (
                                <div className="flex flex-col gap-1">
                                    <span className="text-muted">Completed:</span>
                                    <span className="font-medium">
                                        {dayjs(selectedRun.completed_at).format('MMM D, YYYY HH:mm:ss')}
                                    </span>
                                </div>
                            )}
                            {selectedRun.output?.pr_url && (
                                <div className="flex flex-col gap-1">
                                    <span className="text-muted">Pull request:</span>
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        icon={<IconGithub />}
                                        to={selectedRun.output.pr_url}
                                        targetBlank
                                    >
                                        View PR
                                    </LemonButton>
                                </div>
                            )}
                        </div>

                        {selectedRun.error_message && (
                            <div className="mt-4 p-4 bg-danger-highlight border border-danger rounded">
                                <div className="font-semibold text-danger mb-2">Error</div>
                                <pre className="text-sm whitespace-pre-wrap">{selectedRun.error_message}</pre>
                            </div>
                        )}

                        <LemonDivider className="my-4" />

                        <LemonTabs
                            activeKey="logs"
                            tabs={[
                                {
                                    key: 'logs',
                                    label: 'Logs',
                                    content: <TaskRunLogs logs={logs} loading={logsLoading} />,
                                },
                                {
                                    key: 'output',
                                    label: 'Output',
                                    content: (
                                        <div className="p-4">
                                            {selectedRun.output ? (
                                                <pre className="bg-bg-light p-4 rounded overflow-auto">
                                                    {JSON.stringify(selectedRun.output, null, 2)}
                                                </pre>
                                            ) : (
                                                <p className="text-muted">No output available</p>
                                            )}
                                        </div>
                                    ),
                                },
                            ]}
                        />
                    </div>
                ) : null}
            </div>
        </SceneContent>
    )
}

function formatRunLabel(run: TaskRun): string {
    const date = dayjs(run.created_at)
    const now = dayjs()
    const diffInMinutes = now.diff(date, 'minutes')

    let timeAgo: string
    if (diffInMinutes < 1) {
        timeAgo = 'just now'
    } else if (diffInMinutes < 60) {
        timeAgo = `${diffInMinutes}m ago`
    } else if (diffInMinutes < 1440) {
        const hours = Math.floor(diffInMinutes / 60)
        timeAgo = `${hours}h ago`
    } else {
        const days = Math.floor(diffInMinutes / 1440)
        timeAgo = `${days}d ago`
    }

    const statusEmoji = {
        started: '🔵',
        in_progress: '🟡',
        completed: '✅',
        failed: '❌',
    }[run.status]

    return `${statusEmoji} ${date.format('MMM D, HH:mm')} (${timeAgo})`
}
