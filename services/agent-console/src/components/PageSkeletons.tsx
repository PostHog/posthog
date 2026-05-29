/**
 * Layout-matching skeletons shown while a page's primary data is
 * loading for the first time. Once data arrives the skeleton is
 * replaced by the real component; subsequent refetches show only the
 * `<TopLoadingBar />` and render stale-while-revalidate.
 *
 * The shapes intentionally mirror the real layouts in
 * `pages/AgentsList`, `pages/AgentDetail`, and `pages/SessionDetail`
 * so the swap is jump-free.
 */

'use client'

import { Skeleton } from './Skeleton'

export function AgentsListSkeleton(): React.ReactElement {
    return (
        <div className="mx-auto max-w-6xl px-6 py-6">
            <Skeleton className="h-6 w-32" />
            <Skeleton className="mt-2 h-4 w-72" />
            <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
                <div className="space-y-3">
                    {Array.from({ length: 4 }).map((_, i) => (
                        <div key={i} className="rounded-md border border-border bg-background p-4">
                            <Skeleton className="h-4 w-1/3" />
                            <Skeleton className="mt-2 h-3 w-2/3" />
                            <div className="mt-3 flex gap-3">
                                <Skeleton className="h-3 w-16" />
                                <Skeleton className="h-3 w-12" />
                                <Skeleton className="h-3 w-20" />
                            </div>
                        </div>
                    ))}
                </div>
                <aside className="space-y-3">
                    <div className="rounded-md border border-border bg-background p-4">
                        <Skeleton className="h-3 w-20" />
                        <Skeleton className="mt-3 h-6 w-16" />
                    </div>
                    <div className="rounded-md border border-border bg-background p-4">
                        <Skeleton className="h-3 w-20" />
                        <Skeleton className="mt-3 h-6 w-12" />
                    </div>
                </aside>
            </div>
        </div>
    )
}

export function AgentDetailSkeleton(): React.ReactElement {
    return (
        <div className="mx-auto max-w-5xl px-6 py-6">
            <Skeleton className="h-3 w-32" />
            <div className="mt-3 flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1 space-y-2">
                    <Skeleton className="h-6 w-48" />
                    <Skeleton className="h-4 w-3/4" />
                </div>
                <Skeleton className="h-8 w-36 shrink-0" />
            </div>
            <div className="mt-5 flex gap-4 border-b border-border pb-2">
                <Skeleton className="h-4 w-20" />
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-4 w-20" />
            </div>
            <div className="mt-6 space-y-4">
                {Array.from({ length: 3 }).map((_, i) => (
                    <div key={i} className="rounded-md border border-border bg-background p-4">
                        <Skeleton className="h-4 w-1/4" />
                        <Skeleton className="mt-2 h-3 w-1/2" />
                        <Skeleton className="mt-2 h-3 w-2/3" />
                    </div>
                ))}
            </div>
        </div>
    )
}

export function SessionDetailSkeleton(): React.ReactElement {
    return (
        <div className="flex h-full flex-col px-6 py-6">
            <Skeleton className="h-3 w-40" />
            <div className="mt-3 space-y-2">
                <Skeleton className="h-6 w-1/2" />
                <Skeleton className="h-3 w-1/3" />
            </div>
            <div className="mt-4 flex gap-3">
                {Array.from({ length: 4 }).map((_, i) => (
                    <Skeleton key={i} className="h-14 w-28" />
                ))}
            </div>
            <div className="mt-4 grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
                <div className="space-y-3 rounded-md border border-border bg-background p-4">
                    {Array.from({ length: 4 }).map((_, i) => (
                        <div key={i} className="space-y-2">
                            <Skeleton className="h-3 w-16" />
                            <Skeleton className="h-3 w-full" />
                            <Skeleton className="h-3 w-5/6" />
                        </div>
                    ))}
                </div>
                <div className="space-y-2 rounded-md border border-border bg-background p-4">
                    {Array.from({ length: 8 }).map((_, i) => (
                        <Skeleton key={i} className="h-3 w-full" />
                    ))}
                </div>
            </div>
        </div>
    )
}
