import { BindLogic, useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { RunSurface } from 'products/posthog_ai/frontend/api/runSurface'

import { taskTrackerSceneLogic } from '../taskTrackerSceneLogic'
import { TaskComposer } from './TaskComposer'
import { TaskRunChat } from './TaskRunChat'

export interface SidePanelRunnerImplProps {
    /** Embedded `taskTrackerSceneLogic` key — keeps this instance independent of the `/tasks` scene singleton. */
    panelId: string
}

/**
 * Compact task-run surface for narrow hosts (Max's side panel): the same optimistic
 * create -> pending thread -> live run flow as the `/tasks` scene, without its list/detail chrome or
 * `/tasks/:id` navigation. Binds an embedded `taskTrackerSceneLogic` instance (keyed by `panelId`, see
 * `TaskTrackerSceneLogicProps`) so `TaskComposer` — which reads the unbound `taskTrackerSceneLogic` — resolves
 * this instance instead of the scene's own singleton.
 */
export function SidePanelRunnerImpl({ panelId }: SidePanelRunnerImplProps): JSX.Element {
    return (
        <BindLogic logic={taskTrackerSceneLogic} props={{ panelId }}>
            <SidePanelRunnerContent />
        </BindLogic>
    )
}

function SidePanelRunnerContent(): JSX.Element {
    const { activeCreation } = useValues(taskTrackerSceneLogic)
    const { clearActiveCreation } = useActions(taskTrackerSceneLogic)

    if (!activeCreation) {
        return (
            <div className="flex flex-col h-full min-h-0">
                <TaskComposer />
            </div>
        )
    }

    return (
        <div className="flex flex-col h-full min-h-0">
            <div className="flex items-center justify-end shrink-0 border-b border-primary px-2 py-1">
                <LemonButton size="small" icon={<IconPlus />} onClick={() => clearActiveCreation()}>
                    New task
                </LemonButton>
            </div>
            {activeCreation.taskId && activeCreation.runId ? (
                // `TaskRunChat`'s inner container compensates for the `/tasks` scene's own horizontal margin
                // with `-mx-4`; a `px-4` wrapper here neutralizes that bleed instead of editing the shared
                // component, so it renders flush with the panel edge like the composer and pending states.
                <div className="flex-1 min-h-0 px-4">
                    <TaskRunChat
                        taskId={activeCreation.taskId}
                        runId={activeCreation.runId}
                        streamKey={activeCreation.streamKey}
                    />
                </div>
            ) : (
                <div className="@container/thread flex flex-col flex-1 min-h-0">
                    <RunSurface.Root taskId="" runId={null} streamKey={activeCreation.streamKey} interaction="live">
                        <RunSurface.Thread className="flex-1 min-h-0" listClassName="py-4" rowClassName="px-4" />
                    </RunSurface.Root>
                </div>
            )}
        </div>
    )
}
