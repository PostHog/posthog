import { useActions, useValues } from 'kea'

import { IconExternal, IconGithub, IconPlay } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { taskDetailSceneLogic } from '../taskDetailSceneLogic'
import { taskTrackerSceneLogic } from '../taskTrackerSceneLogic'
import { TaskHeaderActionsSkeleton } from './taskDetailSkeletons'
import { TaskRunLog } from './TaskRunLog'
import { TaskRunSceneShell } from './TaskRunSceneShell'

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
    const { activeCreation } = useValues(taskTrackerSceneLogic)
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

    // When this task was just created optimistically, the seeded run stream lives under the creation's client
    // `streamKey`. Hand it to the run log so it adopts that instance (and renders the thread immediately)
    // instead of cold-bootstrapping a fresh, skeleton-flashing one.
    const isActiveCreation = activeCreation?.taskId === taskId
    const optimisticStreamKey = isActiveCreation ? activeCreation?.streamKey : undefined
    const optimisticRunId = isActiveCreation ? activeCreation?.runId : undefined

    return (
        <TaskRunSceneShell
            task={task}
            selectedRun={selectedRun}
            isHeaderLoading={isHeaderLoading}
            titleActions={titleActions}
            sceneMenuBarEnabled={sceneMenuBarEnabled}
            onArchive={deleteTask}
            taskError={taskError}
            onRetry={loadTask}
            isMobile={isMobile}
        >
            <TaskRunLog taskId={taskId} optimisticStreamKey={optimisticStreamKey} optimisticRunId={optimisticRunId} />
        </TaskRunSceneShell>
    )
}
