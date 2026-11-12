import { LemonSkeleton } from '@posthog/lemon-ui'

import { ContentAutopilotTileSkeleton } from './ContentAutopilotTileSkeleton'

/** The rankings layout while it loads, one placeholder per tile, so nothing moves when the numbers arrive. */
export const ContentAutopilotRankingsSkeleton = (): JSX.Element => (
    <section className="@container/rankings flex flex-col gap-4" data-attr="content-autopilot-rankings-loading">
        <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="flex min-w-0 flex-1 basis-80 flex-col gap-1">
                <LemonSkeleton className="h-5 w-56" />
                <LemonSkeleton className="h-3 w-full max-w-160" />
            </div>
            <LemonSkeleton className="h-8 w-64" />
        </div>
        <div className="grid grid-cols-1 @5xl/rankings:grid-cols-2 gap-4">
            <ContentAutopilotTileSkeleton
                title="Visibility"
                bodyClassName="h-80 p-2"
                skeletonClassName="h-full w-full"
            />
            <ContentAutopilotTileSkeleton title="Brands" skeletonClassName="h-72 w-full" />
        </div>
        <div className="grid grid-cols-1 @3xl/rankings:grid-cols-2 gap-4">
            <ContentAutopilotTileSkeleton title="Sites the engines cite most" />
            <ContentAutopilotTileSkeleton title="Pages the engines cite most" />
        </div>
    </section>
)
