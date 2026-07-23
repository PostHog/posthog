import { BindLogic, useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { RunSurface } from 'products/posthog_ai/frontend/api/runSurface'

import { useAttachedContext } from '../../../hooks/useAttachedContext'
import { useForegroundStream } from '../../../hooks/useForegroundStream'
import { AGENT_TOOL_APPLY_BACK_CONTEXT_ITEM } from '../../../utils/posthogContextBlock'
import { taskTrackerSceneLogic } from '../taskTrackerSceneLogic'
import { TaskComposer } from './TaskComposer'
import { TaskHistoryList, TaskHistoryPreview } from './TaskHistory'
import { TaskRunChat } from './TaskRunChat'

export interface SidePanelRunnerImplProps {
    /** Embedded `taskTrackerSceneLogic` key — keeps this instance independent of the `/tasks` scene singleton. */
    panelId: string
}

/**
 * Top clearance for the side panel's floating pane header: its 40px height plus the 20px gap it kept below
 * itself when it still sat in flow (`SidePanelPaneHeader`'s `h-[40px]` + `mb-5`).
 */
const PANEL_HEADER_CLEARANCE = 'pt-15'

/**
 * Compact task-run surface for narrow hosts (Max's side panel): the same optimistic
 * create -> pending thread -> live run flow as the `/tasks` scene, without its list/detail chrome or
 * `/tasks/:id` navigation. Binds an embedded `taskTrackerSceneLogic` instance (keyed by `panelId`, see
 * `TaskTrackerSceneLogicProps`) so `TaskComposer` — which reads the unbound `taskTrackerSceneLogic` — resolves
 * this instance instead of the scene's own singleton.
 *
 * The side panel's pane header floats over this surface (see `MaxInstance`), so every state below clears it
 * with `PANEL_HEADER_CLEARANCE` at rest — as scroll-content padding where the state scrolls, so the thread
 * (and the welcome column) scroll behind the header, matching the legacy sidebar.
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
    const { toggleHistory, updateActiveCreationRun } = useActions(taskTrackerSceneLogic)

    // This compact surface renders only in Max's side panel, so the run it shows is a foreground
    // stream. Register its `streamKey` (cleared when the panel drops back to the composer/history, and
    // re-pointed when it switches runs). The `/tasks` full-page run view registers its own entry via
    // `TaskRunChat`; registrations are provider-keyed, so co-mounted surfaces don't clobber each other.
    useForegroundStream(activeCreation?.streamKey ?? null)

    // While this side-panel surface is mounted, tell the agent its tool calls are applied back into
    // whatever the user has open (see `useMcpToolApplyBack` consumers). Attached unconditionally —
    // unlike the foreground stream above, the instruction must ride the FIRST send, before a run exists.
    useAttachedContext([AGENT_TOOL_APPLY_BACK_CONTEXT_ITEM])

    if (!activeCreation && historyExpanded) {
        return (
            <div className={cn('flex flex-col h-full min-h-0', PANEL_HEADER_CLEARANCE)}>
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
        // The clearance is scroll-content padding (this column is the scroller), so an overflowing
        // welcome column scrolls behind the floating header.
        return (
            <div
                className={cn(
                    'relative flex flex-col gap-4 pb-7 h-full min-h-0 overflow-y-auto',
                    PANEL_HEADER_CLEARANCE
                )}
            >
                {/* No `items-center` (unlike the legacy welcome block): `TaskComposer` must stretch to full
                width — it centers its own content, same as under the `/tasks` scene's wrapper. */}
                <div className="grow min-h-0 flex flex-col">
                    <TaskComposer />
                </div>
                <TaskHistoryPreview />
            </div>
        )
    }

    // The thread clearance rides `listClassName` (scroll-content padding, not container padding) so rows
    // start below the floating header at rest but scroll up behind it — the legacy sidebar behavior.
    return (
        <div className="flex flex-col h-full min-h-0">
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
                        threadListClassName={cn('pb-4', PANEL_HEADER_CLEARANCE)}
                    />
                </div>
            ) : (
                <div className="@container/thread flex flex-col flex-1 min-h-0">
                    <RunSurface.Root taskId="" runId={null} streamKey={activeCreation.streamKey} interaction="live">
                        <RunSurface.Thread
                            className="flex-1 min-h-0"
                            listClassName={cn('pb-4', PANEL_HEADER_CLEARANCE)}
                            rowClassName="px-4"
                        />
                    </RunSurface.Root>
                </div>
            )}
        </div>
    )
}
