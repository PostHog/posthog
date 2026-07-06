import { lazy, Suspense } from 'react'

import type { ReadonlyRunSurfaceProps } from './ReadonlyRunSurfaceImpl'
import { RunLogSkeleton } from './RunLogSkeleton'

export type { ReadonlyRunSurfaceProps } from './ReadonlyRunSurfaceImpl'

// Heavy chunk (the RunSurface compound — stream logic, virtualized thread, tool/diff renderers) loaded on
// demand; the RunLogSkeleton fallback matches the loaded thread, so the surface keeps its shape across
// chunk-load → bootstrap → first frame. Only `react` + the lightweight skeleton are imported statically — the
// impl is reached solely via dynamic `import()` (the type import below is erased), so the chunk genuinely splits.
const Lazy = lazy(() => import('./ReadonlyRunSurfaceImpl'))

/**
 * Prepackaged read-only run surface, code-split behind a `RunLogSkeleton` fallback. This is the common
 * embed: the inbox detail views (`ArtefactTaskRun` / `AgentRunDetail` / `ReportTasksSection`) drop it in.
 * It renders the run thread (and, for a live run, the meta bars) with no composer and no approval prompt;
 * see `ReadonlyRunSurfaceImpl` for the layout. For a custom layout, compose the `RunSurface` compound
 * directly (api/runSurface).
 */
export function ReadonlyRunSurface(props: ReadonlyRunSurfaceProps): JSX.Element {
    return (
        <Suspense fallback={<RunLogSkeleton />}>
            <Lazy {...props} />
        </Suspense>
    )
}
