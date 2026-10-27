import { memo } from 'react'

import { Skeleton, SkeletonText } from '@posthog/quill-primitives'

import { cn } from 'lib/utils/css-classes'

/**
 * Loading state for "a run/task log is loading" — shared by the runner scene, the lazy `ReadonlyRunSurface`
 * chunk's Suspense fallback, and the `RunSurface` in-stream bootstrap. Mirrors `ThreadView`'s centered `max-w-180`
 * column: a short user bubble on the right, then the agent reply as text lines. Text lines and capped bubble
 * widths keep the shape readable in narrow panels. A quill-primitives-only leaf, so it stays out of the heavy
 * chunk and is safe as a fallback.
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
            <div className={cn('flex flex-col gap-4 w-full max-w-180 mx-auto pt-4 px-3', listClassName)}>
                <div className={cn('flex justify-end w-full', rowClassName)}>
                    <Skeleton className="h-9 w-48 max-w-[80%] rounded-lg" />
                </div>
                <div className={cn('flex flex-col gap-3 w-full', rowClassName)}>
                    <SkeletonText lines={3} className="text-sm" />
                    <SkeletonText lines={2} className="text-sm" maxWidth={90} />
                </div>
            </div>
        </div>
    )
})
