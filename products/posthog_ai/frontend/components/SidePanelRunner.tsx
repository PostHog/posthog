import { lazy, Suspense } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner'

import type { SidePanelRunnerImplProps } from '../scenes/TaskTracker/components/SidePanelRunnerImpl'

export type SidePanelRunnerProps = SidePanelRunnerImplProps

// The compact side-panel task-run surface (composer -> pending thread -> live run, no list/detail chrome) is
// loaded on demand so a consumer that only links to it — e.g. Max's side panel — doesn't statically pull the
// TaskTracker scene's components into its own chunk. Only `react` + a lightweight spinner load eagerly.
const Lazy = lazy(() =>
    import('../scenes/TaskTracker/components/SidePanelRunnerImpl').then((m) => ({ default: m.SidePanelRunnerImpl }))
)

/**
 * Embeddable, code-split compact task-run surface for narrow hosts. Renders the composer, the optimistic
 * pending thread, and the live run — keyed by `panelId` so a host's embedded `taskTrackerSceneLogic` instance
 * stays independent of the `/tasks` scene's own singleton.
 */
export function SidePanelRunner(props: SidePanelRunnerProps): JSX.Element {
    return (
        <Suspense
            fallback={
                <div className="flex flex-1 items-center justify-center">
                    <Spinner className="text-2xl" />
                </div>
            }
        >
            <Lazy {...props} />
        </Suspense>
    )
}
