import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import type { runnerPanelLogicType } from './runnerPanelLogicType'

// The optimistic run opened on send, before the task/run exist. `streamKey` is the client key the pending
// `RunSurface` (and its seeded `runStreamLogic`) bind to; `taskId`/`runId` are filled once known (reserved
// for a future zero-flash in-place handoff — today the scene navigates to the detail page once the run exists).
export interface ActiveCreation {
    streamKey: string
    taskId?: string
    runId?: string
}

// `panelId` is set only by an embedded instance (e.g. Max's side panel runner), which mounts this logic
// under its own key rather than a scene's default singleton. Pass the same `panelId` a paired
// `taskTrackerSceneLogic` instance uses so the two stay keyed together.
export interface RunnerPanelLogicProps {
    panelId?: string
}

export const runnerPanelLogic = kea<runnerPanelLogicType>([
    path(['products', 'posthog_ai', 'frontend', 'logics', 'runnerPanelLogic']),
    props({} as RunnerPanelLogicProps),
    // No `panelId` resolves to the same 'scene' key `taskTrackerSceneLogic` falls back to, so an unkeyed
    // caller pairs with the scene's own singleton.
    key((props) => props.panelId ?? 'scene'),

    actions({
        setActiveCreation: (creation: ActiveCreation) => ({ creation }),
        clearActiveCreation: true,
        toggleHistory: true,
        setHistoryExpanded: (expanded: boolean) => ({ expanded }),
        goBack: true,
        setCameFromHistory: (cameFromHistory: boolean) => ({ cameFromHistory }),
    }),

    reducers({
        // The in-flight optimistic create. While set (and no task is selected) the panel shows the pending
        // run thread instead of the composer.
        activeCreation: [
            null as ActiveCreation | null,
            {
                setActiveCreation: (_, { creation }) => creation,
                clearActiveCreation: () => null,
            },
        ],
        // Whether the panel is showing the full task history list instead of the composer/run.
        historyExpanded: [
            false,
            {
                toggleHistory: (state) => !state,
                setHistoryExpanded: (_, { expanded }) => expanded,
            },
        ],
        // Whether the currently active creation was opened from the expanded history view, so `goBack`
        // knows to return there instead of falling through to the composer — mirrors legacy Max's
        // `backToScreen: 'history'`.
        cameFromHistory: [
            false,
            {
                setCameFromHistory: (_, { cameFromHistory }) => cameFromHistory,
            },
        ],
    }),

    selectors({
        canGoBack: [
            (s) => [s.activeCreation, s.historyExpanded],
            (activeCreation, historyExpanded): boolean => !!activeCreation || historyExpanded,
        ],
    }),

    listeners(({ actions, values }) => ({
        // Opening a task (from the composer or from history) collapses the history list so the run takes
        // over the panel, and remembers whether it came from there — read-then-clear works because
        // reducers for this same dispatch run before listeners.
        setActiveCreation: () => {
            if (values.historyExpanded) {
                actions.setCameFromHistory(true)
                actions.setHistoryExpanded(false)
            } else {
                actions.setCameFromHistory(false)
            }
        },
        // Back walks run -> history-or-composer -> composer.
        goBack: () => {
            if (values.activeCreation) {
                actions.clearActiveCreation()
                if (values.cameFromHistory) {
                    actions.setHistoryExpanded(true)
                }
            } else if (values.historyExpanded) {
                actions.setHistoryExpanded(false)
            }
        },
    })),
])
