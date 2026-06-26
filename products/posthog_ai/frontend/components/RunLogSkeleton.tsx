import { memo } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

/**
 * Loading state for "a run/task log is loading" — shared by the runner scene, the lazy `RunViewer` chunk's
 * Suspense fallback, and `RunViewer`'s in-stream bootstrap. Mirrors `ThreadView`'s centered `max-w-180`
 * column and `MessageTemplate`'s rounded left/right bubbles so the surface keeps its shape when content
 * mounts. A `LemonSkeleton`-only leaf, so it stays out of the heavy chunk and is safe as a fallback.
 */
export const RunLogSkeleton = memo(function RunLogSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col h-full min-h-0 w-full" data-attr="run-log-skeleton">
            <div className="flex flex-col gap-1.5 w-full max-w-180 mx-auto pt-4">
                <div className="flex justify-start w-full">
                    <LemonSkeleton className="h-16 w-3/4 rounded-lg" />
                </div>
                <div className="flex justify-end w-full">
                    <LemonSkeleton className="h-10 w-1/2 rounded-lg" />
                </div>
                <div className="flex justify-start w-full">
                    <LemonSkeleton className="h-24 w-4/5 rounded-lg" />
                </div>
            </div>
        </div>
    )
})
