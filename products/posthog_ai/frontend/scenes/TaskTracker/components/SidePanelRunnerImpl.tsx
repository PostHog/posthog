import { BindLogic, useActions, useValues } from 'kea'

import { IconArrowLeft, IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { RunSurface } from 'products/posthog_ai/frontend/api/runSurface'

import { taskTrackerSceneLogic } from '../taskTrackerSceneLogic'
import { TaskComposer } from './TaskComposer'
import { TaskHistoryList, TaskHistoryPreview } from './TaskHistory'
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
    const { activeCreation, historyExpanded } = useValues(taskTrackerSceneLogic)
    const { clearActiveCreation, toggleHistory, updateActiveCreationRun } = useActions(taskTrackerSceneLogic)

    if (!activeCreation && historyExpanded) {
        return (
            <div className="flex flex-col h-full min-h-0">
                <div className="flex items-center shrink-0 border-b border-primary px-2 py-1">
                    <LemonButton size="small" icon={<IconArrowLeft />} onClick={() => toggleHistory()}>
                        Back
                    </LemonButton>
                </div>
                <div className="flex-1 min-h-0 overflow-y-auto px-4 py-2">
                    <TaskHistoryList />
                </div>
            </div>
        )
    }

    if (!activeCreation) {
        // Mirrors the legacy Max welcome layout: a centered composer with the recent-tasks
        // history pinned as a sibling at the bottom of the panel, not inside the composer column.
        return (
            <div className="relative flex flex-col gap-4 pb-7 h-full min-h-0 overflow-y-auto">
                {/* No `items-center` (unlike the legacy welcome block): `TaskComposer` must stretch to full
                width — it centers its own content, same as under the `/tasks` scene's wrapper. */}
                <div className="grow min-h-0 flex flex-col">
                    <TaskComposer />
                </div>
                <TaskHistoryPreview />
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
                        onRunStarted={updateActiveCreationRun}
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
