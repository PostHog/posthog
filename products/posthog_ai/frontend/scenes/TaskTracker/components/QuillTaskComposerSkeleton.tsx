import { Skeleton } from '@posthog/quill-primitives'

export function QuillTaskComposerSkeleton(): JSX.Element {
    return (
        <div data-quill aria-hidden className="flex flex-col gap-1">
            <div className="rounded-sm border border-border">
                <Skeleton className="h-16 w-full" />
            </div>
            <div className="flex h-6 items-center gap-1 px-1">
                <Skeleton className="size-6" />
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-4 w-32" />
            </div>
        </div>
    )
}
