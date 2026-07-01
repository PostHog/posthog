import { useActions, useValues } from 'kea'

import { IconArchive, IconExternal, IconGithub, IconPlay } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

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

import { taskDetailSceneLogic } from '../taskDetailSceneLogic'
import { TaskHeaderActionsSkeleton, TaskPanelSkeleton, TaskRunMetadataSkeleton } from './taskDetailSkeletons'
import { TaskErrorBanner } from './TaskErrorBanner'
import { TaskRunLog } from './TaskRunLog'
import { TaskRunMetadata } from './TaskRunMetadata'

export interface TaskDetailPageProps {
    taskId: string
    /** Mobile shows the single-column layout, where a back button is needed to return to the list. */
    isMobile: boolean
}

export function TaskDetailPage({ taskId, isMobile }: TaskDetailPageProps): JSX.Element {
    const sceneLogic = taskDetailSceneLogic({ taskId })
    const { task, taskNotFound, taskError, runs, selectedRun, isTaskPending, isHeaderLoading } = useValues(sceneLogic)
    const { runTask, deleteTask, loadTask } = useActions(sceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const sceneMenuBarEnabled = !!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]

    if (taskNotFound && !task) {
        return <NotFound object="task" />
    }

    if (!isTaskPending && !task && !taskError) {
        return <NotFound object="task" />
    }

    const latestRun = runs.length > 0 ? runs[0] : null
    const isLatestRunInProgress = latestRun?.status === 'in_progress' || latestRun?.status === 'queued'
    const isLatestRunCompleted = latestRun?.status === 'completed'
    const runButtonText = runs.length === 0 ? 'Run task' : 'Retry task'

    const prUrl = selectedRun?.output?.pr_url as string | undefined
    const titleActions =
        isHeaderLoading || !task ? (
            <TaskHeaderActionsSkeleton />
        ) : (
            <div className="flex items-center gap-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconExternal />}
                    className="hidden lg:inline-flex"
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
        <SceneContent className="h-full min-h-0 gap-y-0">
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
                {isHeaderLoading || !task ? (
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
                <TaskErrorBanner
                    title="We couldn't load this task."
                    message={taskError}
                    onRetry={loadTask}
                    dataAttr="task-load-error"
                    className="max-w-200"
                />
            ) : (
                <>
                    {taskError && (
                        <TaskErrorBanner
                            title="We couldn't load this task."
                            message={taskError}
                            onRetry={loadTask}
                            dataAttr="task-load-error"
                            className="max-w-200"
                        />
                    )}

                    <header className="flex flex-col gap-y-2 mt-4">
                        <SceneTitleSection
                            name={task?.title || 'Task'}
                            description={null}
                            resourceType={{ type: 'task' }}
                            isLoading={isHeaderLoading}
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

                        {isHeaderLoading ? (
                            <TaskRunMetadataSkeleton />
                        ) : (
                            selectedRun && <TaskRunMetadata selectedRun={selectedRun} />
                        )}

                        <LemonDivider className="hidden lg:block mb-0 mt-2" />
                    </header>

                    <TaskRunLog taskId={taskId} />
                </>
            )}
        </SceneContent>
    )
}
