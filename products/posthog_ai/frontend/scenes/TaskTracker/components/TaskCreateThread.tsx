import { RunSurface } from 'products/posthog_ai/frontend/api/runSurface'

import { TaskHeaderActionsSkeleton } from './taskDetailSkeletons'
import { TaskRunSceneShell } from './TaskRunSceneShell'

export interface TaskCreateThreadProps {
    /** Client stream key the optimistic `runStreamLogic` was seeded under (see `taskTrackerSceneLogic.submit`). */
    streamKey: string
    /** Mobile composer pane renders this too; forwarded to the shell for the back button. */
    isMobile: boolean
}

/**
 * The optimistic create thread shown the instant the user hits send, before the task/run exist. It renders the
 * same scene shell as the detail page — in its all-loading state, since the task/title/run don't exist yet, so
 * the header shows skeletons — wrapped around the pending `RunSurface` (no `runId`): `taskTrackerSceneLogic` has
 * already seeded the bound `runStreamLogic` (keyed by `streamKey`) with the typed message + provisioning
 * indicator via `startOptimisticRun`, so this just renders that thread. Rendering the identical shell here is
 * what makes the `/tasks/new → /tasks/:id` handoff seamless — once the run is created the scene navigates to the
 * detail page, which adopts the same seeded stream so only the continuous thread underneath persists.
 */
export function TaskCreateThread({ streamKey, isMobile }: TaskCreateThreadProps): JSX.Element {
    return (
        <TaskRunSceneShell
            task={null}
            selectedRun={null}
            isHeaderLoading
            titleActions={<TaskHeaderActionsSkeleton />}
            sceneMenuBarEnabled={false}
            onArchive={() => {}}
            taskError={null}
            onRetry={() => {}}
            isMobile={isMobile}
        >
            <div className="@container/thread flex flex-col h-full -mx-4">
                <RunSurface.Root taskId="" runId={null} streamKey={streamKey} interaction="live">
                    <RunSurface.Thread className="flex-1 min-h-0" listClassName="py-4" rowClassName="px-4" />
                </RunSurface.Root>
            </div>
        </TaskRunSceneShell>
    )
}
