import { Skeleton } from '@posthog/quill'

import { AiVisibilityCard } from './AiVisibilityCard'

/** The rankings layout while it loads, one placeholder per tile, so nothing moves when the numbers arrive. */
export const ContentAutopilotRankingsSkeleton = (): JSX.Element => (
    <section
        className="@container/rankings flex flex-col gap-4"
        data-attr="content-autopilot-rankings-loading"
        aria-busy
    >
        <div className="flex min-w-0 flex-col gap-1">
            <Skeleton className="h-5 w-56 max-w-full" />
            <Skeleton className="h-3 w-full max-w-160" />
        </div>
        <div className="grid grid-cols-1 @5xl/rankings:grid-cols-2 items-start gap-4">
            <AiVisibilityCard title="Visibility">
                <Skeleton className="h-64 w-full" />
            </AiVisibilityCard>
            <AiVisibilityCard title="Brands">
                <Skeleton className="h-64 w-full" />
            </AiVisibilityCard>
        </div>
        <div className="grid grid-cols-1 @3xl/rankings:grid-cols-2 gap-4">
            <AiVisibilityCard title="Sites the engines cite most">
                <Skeleton className="h-48 w-full" />
            </AiVisibilityCard>
            <AiVisibilityCard title="Pages the engines cite most">
                <Skeleton className="h-48 w-full" />
            </AiVisibilityCard>
        </div>
    </section>
)
