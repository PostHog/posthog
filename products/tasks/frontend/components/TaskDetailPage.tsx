import { useActions, useValues } from 'kea'

import { IconArchive, IconExternal, IconPlay } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
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

import { taskDetailSceneLogic } from '../logics/taskDetailSceneLogic'
import { PrBadge } from './PrBadge'
import { TaskRunItem } from './TaskRunItem'
import { TaskSessionView } from './TaskSessionView'

export interface TaskDetailPageProps {
    taskId: string
}

export function TaskDetailPage({ taskId }: TaskDetailPageProps): JSX.Element {
    const sceneLogic = taskDetailSceneLogic({ taskId })
    const {
        task,
        taskLoading,
        runs,
        selectedRunId,
        selectedRun,
        runsLoading,
        logs,
        logsLoading,
        shouldPoll,
        events,
        isStreaming,
        streamingFailed,
    } = useValues(sceneLogic)
    const { setSelectedRunId, runTask, deleteTask, updateTask, startStreaming } = useActions(sceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const sceneMenuBarEnabled = !!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]

    if (taskLoading && !task) {
        return (
            <div className="flex items-center justify-center h-32">
                <Spinner />
            </div>
        )
    }

    if (!task) {
        return <NotFound object="task" />
    }

    const hasBeenRun = runs.length > 0
    const latestRun = runs.length > 0 ? runs[0] : null
    const isLatestRunInProgress = latestRun?.status === 'in_progress' || latestRun?.status === 'queued'
    const isLatestRunCompleted = latestRun?.status === 'completed'
    const runButtonText = !hasBeenRun ? 'Run task' : isLatestRunCompleted ? 'Run again' : 'Retry task'

    const prUrl = selectedRun?.output?.pr_url as string | undefined

    return (
        <SceneContent className="flex-1 min-h-0">
            {sceneMenuBarEnabled && (
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

                {runs.length > 0 && (
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
                                        onClick={() => setSelectedRunId(run.id, taskId)}
                                    />
                                ))}
                            </div>
                        </ScenePanelInfoSection>
                    </>
                )}
            </ScenePanel>

            <SceneTitleSection
                name={task?.title}
                description={null}
                resourceType={{ type: 'task' }}
                isLoading={false}
                canEdit={true}
                saveOnBlur
                renameDebounceMs={0}
                onNameChange={(value) => {
                    const title = value.trim()
                    if (title && title !== task.title) {
                        updateTask({ data: { title } })
                    }
                }}
                forceBackTo={{
                    key: 'tasks',
                    name: 'Tasks',
                    path: urls.taskTracker(),
                }}
                actions={
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconExternal />}
                            onClick={() => window.open(`posthog-code://task/${task.id}`, '_blank')}
                        >
                            Open in PostHog Code
                        </LemonButton>
                        <PrBadge prUrl={prUrl} />
                        {!isLatestRunInProgress && (
                            <LemonButton type="primary" size="small" icon={<IconPlay />} onClick={runTask}>
                                {runButtonText}
                            </LemonButton>
                        )}
                    </div>
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
            ) : selectedRun ? (
                <div className="flex-1 min-h-0 overflow-hidden">
                    <TaskSessionView
                        taskId={taskId}
                        logs={logs}
                        logsLoading={logsLoading}
                        events={events}
                        isPolling={shouldPoll}
                        isStreaming={isStreaming}
                        run={selectedRun}
                        streamingFailed={streamingFailed}
                        onRetryStream={startStreaming}
                    />
                </div>
            ) : null}
        </SceneContent>
    )
}
