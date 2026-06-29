import { lazy, Suspense } from 'react'

import { RunLogSkeleton } from './RunLogSkeleton'
import type { RunViewerProps } from './RunViewerImpl'

export type { RunViewerProps } from './RunViewerImpl'

// Heavy chunk (stream logic, virtualized thread, tool/diff renderers) loaded on demand; the RunLogSkeleton
// fallback matches the loaded thread, so the surface keeps its shape across chunk-load → bootstrap → first
// frame. Only `react` + the lightweight skeleton are imported statically — the impl is reached solely via
// dynamic `import()` (the type import below is erased), so the chunk genuinely splits.
const LazyRunViewer = lazy(() => import('./RunViewerImpl').then((m) => ({ default: m.RunViewer })))

/**
 * Embeddable run surface — binds the stream logic and renders the default layout, code-split behind a
 * `RunLogSkeleton` fallback. This is the common embed: all four consumers (the runner scene's
 * `TaskRunChat`, and the inbox `ArtefactTaskRun` / `AgentRunDetail` / `ReportTasksSection`) use this
 * prepackaged form. The compound (`Root` + slots) stays internal to `RunViewerImpl`, backing the default
 * layout — slot atoms aren't surfaced because no consumer composes them and lazy-wrapping each would only
 * add Suspense boundaries that never fire.
 */
export function RunViewer(props: RunViewerProps): JSX.Element {
    return (
        <Suspense fallback={<RunLogSkeleton />}>
            <LazyRunViewer {...props} />
        </Suspense>
    )
}
