import { StartupRunChat } from './StartupRunChat'
import { TaskRunSceneShell } from './TaskRunSceneShell'

export interface TaskCreateThreadProps {
    /** Client stream key the optimistic `runStreamLogic` was seeded under (see `taskTrackerSceneLogic.submit`). */
    streamKey: string
    /** Mobile composer pane renders this too; forwarded to the shell for the back button. */
    isMobile: boolean
}

/**
 * The optimistic create thread shown the instant the user hits send, before the task/run exist. It renders the
 * same scene shell as the detail page, with metadata omitted until the task/run exist,
 * wrapped around the pending `RunSurface` (no `runId`): `taskTrackerSceneLogic` has
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
            sceneMenuBarEnabled={false}
            onArchive={() => {}}
            taskError={null}
            onRetry={() => {}}
            isMobile={isMobile}
        >
            <StartupRunChat streamKey={streamKey} escapeScope="chat" />
        </TaskRunSceneShell>
    )
}
