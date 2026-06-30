import { RunSurface } from 'products/posthog_ai/frontend/api/runSurface'

export interface TaskCreateThreadProps {
    /** Client stream key the optimistic `runStreamLogic` was seeded under (see `taskTrackerSceneLogic.submit`). */
    streamKey: string
}

/**
 * The optimistic create thread shown the instant the user hits send, before the task/run exist. It composes the
 * pending `RunSurface` (no `runId`): `taskTrackerSceneLogic` has already seeded the bound `runStreamLogic`
 * (keyed by `streamKey`) with the typed message + provisioning indicator via `startOptimisticRun`, so this just
 * renders that thread. Once the run is created the scene navigates to the detail page, which streams it.
 */
export function TaskCreateThread({ streamKey }: TaskCreateThreadProps): JSX.Element {
    return (
        <div className="@container/thread flex flex-col h-full -mx-4">
            <RunSurface.Root taskId="" runId={null} streamKey={streamKey} interaction="live">
                <RunSurface.Thread className="flex-1 min-h-0" listClassName="py-4" rowClassName="px-4" />
            </RunSurface.Root>
        </div>
    )
}
