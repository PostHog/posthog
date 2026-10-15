import { Skeleton } from '@posthog/quill'

/** The repository picker, the input and the control row at their loaded sizes, so the page does not jump when the composer chunk lands. */
export function SpaceTaskComposerSkeleton(): JSX.Element {
    return (
        <div aria-hidden className="flex flex-col gap-2">
            <Skeleton className="h-7 w-36" />
            <div className="flex flex-col gap-1">
                <div className="rounded-sm border border-border">
                    <Skeleton className="h-16 w-full" />
                </div>
                <div className="flex h-6 items-center gap-1 px-1">
                    <Skeleton className="size-6" />
                    <Skeleton className="h-4 w-24" />
                    <Skeleton className="h-4 w-32" />
                </div>
            </div>
        </div>
    )
}
