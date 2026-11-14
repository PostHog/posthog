import '~/queries/nodes/InsightViz/InsightViz.scss'

import { Skeleton } from '@posthog/quill'

import { QuillInsightVisualizationSkeleton } from '~/lib/components/Cards/InsightCard/QuillInsightVisualizationSkeleton'

export function QuillInsightSkeleton(): JSX.Element {
    return (
        <div className="scene-content relative z-10 flex flex-col gap-4" aria-busy="true">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2">
                    <Skeleton className="size-7 shrink-0" />
                    <Skeleton className="h-6 w-64 max-w-full" />
                </div>

                <div className="flex flex-wrap gap-2">
                    <Skeleton className="h-7 w-32" />
                    <Skeleton className="h-7 w-24" />
                    <Skeleton className="h-7 w-14" />
                </div>
            </div>

            <div className="flex flex-col gap-2">
                <Skeleton className="h-4 w-3/4 max-w-full" />
                <Skeleton className="h-4 w-1/2 max-w-full" />
                <Skeleton className="h-3 w-64 max-w-full" />
            </div>

            <div className="flex flex-col gap-4 rounded border bg-surface-primary p-4">
                <div className="flex flex-wrap justify-center gap-x-4 gap-y-2">
                    <Skeleton className="h-3 w-28" />
                    <Skeleton className="h-3 w-24" />
                    <Skeleton className="h-3 w-28" />
                    <Skeleton className="h-3 w-24" />
                </div>
                <div className="InsightVizDisplay min-h-(--insight-viz-min-height)">
                    <QuillInsightVisualizationSkeleton />
                </div>
            </div>
        </div>
    )
}
