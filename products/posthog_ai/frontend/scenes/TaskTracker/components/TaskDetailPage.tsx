import { useActions, useValues } from 'kea'

import { IconArchive, IconExternal, IconGithub, IconPlay } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonSkeleton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import {
    SceneMenuBar,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarSeparator,
} from '~/layout/scenes/components/SceneMenuBar'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'

import { RunLogSkeleton } from 'products/posthog_ai/frontend/api/primitives'

import { TaskRun } from '../../../types/taskTypes'
import { taskDetailSceneLogic } from '../taskDetailSceneLogic'
import { TaskRunChat } from './TaskRunChat'

export interface TaskDetailPageProps {
    taskId: string
    /** Mobile shows the single-column layout, where a back button is needed to return to the list. */
    isMobile: boolean
}

export function TaskDetailPage({ taskId, isMobile }: TaskDetailPageProps): JSX.Element {
    const sceneLogic = taskDetailSceneLogic({ taskId })
    const {
        task,
        taskLoading,
        taskNotFound,
        taskError,
        runs,
        selectedRun,
        selectedRunId,
        runsLoading,
        runsError,
        selectedRunDataLoading,
        selectedRunNotFound,
        selectedRunError,
    } = useValues(sceneLogic)
    const { runTask, deleteTask, loadTask, loadTaskRuns, loadSelectedTaskRun } = useActions(sceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const sceneMenuBarEnabled = !!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]

    if (taskNotFound && !task) {
        return <NotFound object="task" />
    }

    const isTaskPending = taskLoading && !task

    if (!isTaskPending && !task && !taskError) {
        return <NotFound object="task" />
    }

    const hasBeenRun = runs.length > 0
    const latestRun = runs.length > 0 ? runs[0] : null
    const isLatestRunInProgress = latestRun?.status === 'in_progress' || latestRun?.status === 'queued'
    const isLatestRunCompleted = latestRun?.status === 'completed'
    const runButtonText = !hasBeenRun ? 'Run task' : 'Retry task'

    const prUrl = selectedRun?.output?.pr_url as string | undefined
    const titleActions =
        isTaskPending || !task ? (
            <TaskActionsSkeleton />
        ) : (
            <div className="flex items-center gap-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconExternal />}
                    onClick={() => window.open(`posthog-code://task/${task.id}`, '_blank')}
                >
                    Open in PostHog Code
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
                {!isLatestRunInProgress && !isLatestRunCompleted && (
                    <LemonButton type="primary" size="small" icon={<IconPlay />} onClick={runTask}>
                        {runButtonText}
                    </LemonButton>
                )}
            </div>
        )

    return (
        <SceneContent className="h-full min-h-0">
            {sceneMenuBarEnabled && task && (
                <SceneMenuBar>
                    <SceneMenuBarMenu label="File" dataAttr="task-menubar-file">
                        <SceneMenuBarFileItems dataAttrKey="task" />
                        <SceneMenuBarSeparator />
                        <SceneMenuBarItem variant="destructive" onClick={deleteTask} data-attr="task-menubar-archive">
                            <IconArchive />
                            Archive task
                        </SceneMenuBarItem>
                    </SceneMenuBarMenu>
                </SceneMenuBar>
            )}
            <ScenePanel>
                {isTaskPending || !task ? (
                    <TaskPanelSkeleton />
                ) : (
                    <>
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
                                <IconArchive />
                                Archive task
                            </ButtonPrimitive>
                        </ScenePanelActionsSection>
                    </>
                )}
            </ScenePanel>

            {taskError && !task ? (
                <TaskLoadErrorBanner message={taskError} onRetry={loadTask} />
            ) : (
                <>
                    {taskError && <TaskLoadErrorBanner message={taskError} onRetry={loadTask} />}

                    <SceneTitleSection
                        name={task?.title || 'Task'}
                        description={null}
                        resourceType={{ type: 'task' }}
                        isLoading={isTaskPending}
                        canEdit={false}
                        forceBackTo={
                            isMobile
                                ? {
                                      key: 'tasks',
                                      name: 'Tasks',
                                      path: urls.taskTracker(),
                                  }
                                : undefined
                        }
                        actions={titleActions}
                    />

                    {selectedRun && <TaskRunMetadata selectedRun={selectedRun} />}

                    <LemonDivider />

                    <TaskRunLogState
                        taskId={taskId}
                        selectedRun={selectedRun}
                        selectedRunId={selectedRunId}
                        runsLength={runs.length}
                        runsLoading={runsLoading}
                        runsError={runsError}
                        selectedRunDataLoading={selectedRunDataLoading}
                        selectedRunNotFound={selectedRunNotFound}
                        selectedRunError={selectedRunError}
                        onRetryRuns={loadTaskRuns}
                        onRetrySelectedRun={loadSelectedTaskRun}
                    />
                </>
            )}
        </SceneContent>
    )
}

function TaskPanelSkeleton(): JSX.Element {
    return (
        <ScenePanelInfoSection>
            <div className="flex flex-col gap-3">
                <div>
                    <div className="text-xs text-muted mb-1">Task ID</div>
                    <LemonSkeleton className="h-5 w-24" />
                </div>
                <div>
                    <div className="text-xs text-muted mb-1">Repository</div>
                    <LemonSkeleton className="h-5 w-36" />
                </div>
                <div>
                    <div className="text-xs text-muted mb-1">Created by</div>
                    <LemonSkeleton className="h-5 w-32" />
                </div>
                <div>
                    <div className="text-xs text-muted mb-1">Created</div>
                    <LemonSkeleton className="h-5 w-40" />
                </div>
            </div>
        </ScenePanelInfoSection>
    )
}

function TaskActionsSkeleton(): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <LemonSkeleton className="h-7 w-40" />
            <LemonSkeleton className="h-7 w-24" />
        </div>
    )
}

function TaskLoadErrorBanner({ message, onRetry }: { message: string; onRetry: () => void }): JSX.Element {
    return (
        <LemonBanner
            type="error"
            className="max-w-200"
            action={{
                children: 'Retry',
                onClick: onRetry,
            }}
            data-attr="task-load-error"
        >
            <p>We couldn't load this task.</p>
            <p className="text-muted mb-0">{message}</p>
        </LemonBanner>
    )
}

function TaskRunsErrorBanner({ message, onRetry }: { message: string; onRetry: () => void }): JSX.Element {
    return (
        <LemonBanner
            type="error"
            action={{
                children: 'Retry',
                onClick: onRetry,
            }}
            data-attr="task-runs-load-error"
        >
            <p>We couldn't load this task's runs.</p>
            <p className="text-muted mb-0">{message}</p>
        </LemonBanner>
    )
}

function TaskRunMetadata({ selectedRun }: { selectedRun: TaskRun }): JSX.Element {
    return (
        <div className="flex items-center gap-4 text-xs text-muted">
            <dl className="inline-flex gap-1 items-center">
                <dt className="m-0">Created:</dt>
                <dd className="m-0 inline-flex items-center">
                    <TZLabel time={selectedRun.created_at} showSeconds />
                </dd>
            </dl>
            {selectedRun.completed_at && (
                <dl className="inline-flex gap-1 items-center">
                    <dt className="m-0">Completed:</dt>
                    <dd className="m-0 inline-flex items-center">
                        <TZLabel time={selectedRun.completed_at} showSeconds />
                    </dd>
                </dl>
            )}
            {selectedRun.completed_at && (
                <dl className="inline-flex gap-1 items-center">
                    <dt className="m-0">Duration:</dt>
                    <dd className="m-0 inline-flex items-center">
                        {humanFriendlyDuration(dayjs(selectedRun.completed_at).diff(selectedRun.created_at, 'second'))}
                    </dd>
                </dl>
            )}
        </div>
    )
}

function TaskRunLogState({
    taskId,
    selectedRun,
    selectedRunId,
    runsLength,
    runsLoading,
    runsError,
    selectedRunDataLoading,
    selectedRunNotFound,
    selectedRunError,
    onRetryRuns,
    onRetrySelectedRun,
}: {
    taskId?: string
    selectedRun: TaskRun | null
    selectedRunId: string | null
    runsLength: number
    runsLoading: boolean
    runsError: string | null
    selectedRunDataLoading: boolean
    selectedRunNotFound: boolean
    selectedRunError: string | null
    onRetryRuns: () => void
    onRetrySelectedRun: () => void
}): JSX.Element | null {
    if (runsError) {
        return <TaskRunsErrorBanner message={runsError} onRetry={onRetryRuns} />
    }
    if (runsLoading && runsLength === 0) {
        return <RunLogSkeleton />
    }
    if (selectedRunNotFound) {
        return <NotFound object="task run" className="m-0 py-8" />
    }
    if (selectedRunError) {
        return <TaskRunsErrorBanner message={selectedRunError} onRetry={onRetrySelectedRun} />
    }
    if (selectedRunDataLoading && !selectedRun) {
        return <RunLogSkeleton />
    }
    if (runsLength === 0 && !selectedRunId) {
        return (
            <div className="text-center py-16">
                <p className="text-muted">This task hasn't been run yet</p>
            </div>
        )
    }
    if (taskId && selectedRun) {
        return (
            <div className="flex-1 min-h-0 overflow-hidden -mr-4 pr-4">
                <TaskRunChat taskId={taskId} runId={selectedRun.id} />
            </div>
        )
    }
    return selectedRunId ? <RunLogSkeleton /> : null
}
