import { BindLogic, useActions, useValues } from 'kea'
import { ReactNode, useRef } from 'react'

import { LemonDivider } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { useAttachedContext } from '../../../hooks/useAttachedContext'
import { useForegroundStream } from '../../../hooks/useForegroundStream'
import { useThreadSkin } from '../../../hooks/useThreadSkin'
import type { ComposerOverride } from '../../../logics/composerOverrideLogic'
import type { AttachedContextItem } from '../../../types/contextTypes'
import { AGENT_TOOL_APPLY_BACK_CONTEXT_ITEM } from '../../../utils/posthogContextBlock'
import { taskTrackerSceneLogic } from '../taskTrackerSceneLogic'
import { StartupRunChat } from './StartupRunChat'
import { TaskComposer } from './TaskComposer'
import { TaskHistoryPanel, TaskHistoryPreview } from './TaskHistory'
import { TaskRunChat } from './TaskRunChat'

export interface SidePanelRunnerImplProps {
    /** Embedded `taskTrackerSceneLogic` key — keeps this instance independent of the `/tasks` scene singleton. */
    panelId: string
    composer?: ReactNode
    attachApplyBackInstructions?: boolean
    /** Context exclusive to this runner, rather than the app-wide attached-context registry. */
    contextItems?: AttachedContextItem[]
    composerOverride?: ComposerOverride
    welcomeHeadlines?: string[]
}

/**
 * Compact task-run surface for narrow hosts (Max's side panel): the same optimistic
 * create -> pending thread -> live run flow as the `/tasks` scene, without its list/detail chrome or
 * `/tasks/:id` navigation. Binds an embedded `taskTrackerSceneLogic` instance (keyed by `panelId`, see
 * `TaskTrackerSceneLogicProps`) so `TaskComposer` — which reads the unbound `taskTrackerSceneLogic` — resolves
 * this instance instead of the scene's own singleton.
 */
export function SidePanelRunnerImpl({
    panelId,
    composer,
    attachApplyBackInstructions = true,
    contextItems,
    composerOverride,
    welcomeHeadlines,
}: SidePanelRunnerImplProps): JSX.Element {
    return (
        <BindLogic logic={taskTrackerSceneLogic} props={{ panelId, contextItems, composerOverride, welcomeHeadlines }}>
            <SidePanelRunnerContent
                composer={composer}
                attachApplyBackInstructions={attachApplyBackInstructions}
                contextItems={contextItems}
            />
        </BindLogic>
    )
}

function SidePanelRunnerContent({
    composer,
    attachApplyBackInstructions,
    contextItems,
}: {
    composer?: ReactNode
    attachApplyBackInstructions: boolean
    contextItems?: AttachedContextItem[]
}): JSX.Element {
    const {
        activeCreation,
        historyExpanded,
        effectiveComposerOverride: composerOverride,
    } = useValues(taskTrackerSceneLogic)
    const { updateActiveCreationRun, setStartupDraft } = useActions(taskTrackerSceneLogic)
    const startupFocusedRef = useRef(false)
    // The quill host draws its own frame and header divider, and its thread carries no outer margin.
    const lemonChrome = useThreadSkin() === 'lemon'

    // This compact surface renders only in Max's side panel, so the run it shows is a foreground
    // stream. Register the startup stream here; once a run exists, `TaskRunChat` registers the key it
    // resolves, which can be a retained alias. Registrations are provider-keyed, so co-mounted surfaces
    // don't clobber each other.
    useForegroundStream(
        activeCreation && !(activeCreation.taskId && activeCreation.runId) ? activeCreation.streamKey : null
    )

    // Edit-capable hosts attach this before the first send, before a run exists. Question-only
    // hosts provide their own instructions instead of advertising edits to the open page.
    useAttachedContext(attachApplyBackInstructions ? [AGENT_TOOL_APPLY_BACK_CONTEXT_ITEM] : null)

    // `!composer`: a host that supplies its own composer offers no way into the history list, and the
    // panel state is shared across hosts — so an expanded history left behind by another one must not
    // take the place of that composer.
    if (!activeCreation && historyExpanded && !composer) {
        return <TaskHistoryPanel />
    }

    if (!activeCreation) {
        if (composer) {
            return <div className="flex-1 min-h-0 overflow-y-auto">{composer}</div>
        }
        // Mirrors the legacy Max welcome layout: a centered composer with the recent-tasks
        // history pinned as a sibling at the bottom of the panel, not inside the composer column.
        return (
            <div className="relative flex flex-col gap-4 pb-7 h-full min-h-0 overflow-y-auto">
                {/* No `items-center` (unlike the legacy welcome block): `TaskComposer` must stretch to full
                width — it centers its own content, same as under the `/tasks` scene's wrapper. */}
                <div className="grow min-h-0 flex flex-col">
                    <TaskComposer />
                </div>
                {!composerOverride?.hideRecentTasks && <TaskHistoryPreview />}
            </div>
        )
    }

    return (
        <div className="flex flex-col h-full min-h-0">
            {lemonChrome && <LemonDivider className="my-0" />}
            {activeCreation.taskId && activeCreation.runId ? (
                // `TaskRunChat`'s inner container compensates for the `/tasks` scene's own horizontal margin
                // with `-mx-4`; a `px-4` wrapper here neutralizes that bleed instead of editing the shared
                // component, so it renders flush with the panel edge like the composer and pending states.
                <div className={cn('flex-1 min-h-0', lemonChrome && 'px-4')}>
                    <TaskRunChat
                        taskId={activeCreation.taskId}
                        runId={activeCreation.runId}
                        streamKey={activeCreation.streamKey}
                        interactionKey={activeCreation.interactionKey}
                        onRunStarted={updateActiveCreationRun}
                        escapeScope="composer"
                        initialDraft={activeCreation.draft}
                        onDraftAdopted={() => setStartupDraft('')}
                        autoFocus={startupFocusedRef.current}
                        contextItems={contextItems}
                    />
                </div>
            ) : (
                <div className="flex-1 min-h-0 px-4">
                    <StartupRunChat
                        streamKey={activeCreation.streamKey}
                        focusedRef={startupFocusedRef}
                        contextItems={contextItems}
                    />
                </div>
            )}
        </div>
    )
}
