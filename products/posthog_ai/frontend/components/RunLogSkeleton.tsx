import { memo } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

/**
 * Loading state for "a run/task log is loading" — shared by the runner scene, the lazy `ReadonlyRunSurface`
 * chunk's Suspense fallback, and the `RunSurface` in-stream bootstrap. Mirrors `ThreadView`'s centered `max-w-180`
 * column and `MessageTemplate`'s rounded left/right bubbles so the surface keeps its shape when content
 * mounts. A `LemonSkeleton`-only leaf, so it stays out of the heavy chunk and is safe as a fallback.
 */
export const RunLogSkeleton = memo(function RunLogSkeleton({
    className,
    listClassName,
    rowClassName,
}: {
    className?: string
    listClassName?: string
    rowClassName?: string
}): JSX.Element {
    return (
        <div className={cn('flex flex-col h-full min-h-0 w-full', className)} data-attr="run-log-skeleton">
            <div className={cn('flex flex-col gap-1.5 w-full max-w-180 mx-auto pt-4', listClassName)}>
                <div className={cn('flex justify-end w-full', rowClassName)}>
                    <LemonSkeleton className="h-16 w-3/4 rounded-lg" />
                </div>
                <div className={cn('flex justify-start w-full', rowClassName)}>
                    <LemonSkeleton className="h-10 w-1/2 rounded-lg" />
                </div>
                <div className={cn('flex justify-end w-full', rowClassName)}>
                    <LemonSkeleton className="h-24 w-4/5 rounded-lg" />
                </div>
            </div>
        </div>
    )
})
