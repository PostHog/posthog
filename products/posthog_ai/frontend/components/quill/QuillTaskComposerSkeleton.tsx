import { Skeleton } from '@posthog/quill-primitives'

export function QuillTaskComposerSkeleton(): JSX.Element {
    return (
        <div data-quill aria-hidden className="flex flex-col rounded-sm border border-[var(--input)] bg-[var(--card)]">
            <div className="flex min-h-10 items-center px-2.5">
                <Skeleton className="h-3.5 w-48 rounded-sm" />
            </div>
            <div className="flex h-8 items-center gap-1 pr-1 pb-1 pl-1.5">
                <Skeleton className="mx-1 size-4 rounded-sm" />
                <Skeleton className="ml-2 h-3.5 w-28 rounded-sm" />
                <Skeleton className="ml-3 h-3.5 w-32 rounded-sm" />
                <div className="ml-auto flex items-center gap-2">
                    <Skeleton className="h-3.5 w-24 rounded-sm" />
                    <Skeleton className="size-7 rounded-sm" />
                </div>
            </div>
        </div>
    )
}
