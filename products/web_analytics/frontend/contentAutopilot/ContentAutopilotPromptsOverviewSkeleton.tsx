import { LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'

const KPI_CARDS = 5

const TileSkeleton = ({ title, bodyClassName }: { title: string; bodyClassName: string }): JSX.Element => (
    <PagePerformanceCard className="min-w-0">
        <PagePerformanceCardHeader title={title} />
        <div className="p-3">
            <LemonSkeleton className={bodyClassName} />
        </div>
    </PagePerformanceCard>
)

/** The overview's layout while it loads, one placeholder per tile, so nothing moves when the numbers arrive. */
export const ContentAutopilotPromptsOverviewSkeleton = (): JSX.Element => (
    <section
        className="@container/prompts-overview flex flex-col gap-4"
        data-attr="content-autopilot-prompts-overview-loading"
    >
        <div className="flex flex-col gap-1">
            <LemonSkeleton className="h-5 w-56" />
            <LemonSkeleton className="h-3 w-96 max-w-full" />
        </div>
        <div className="grid grid-cols-2 @3xl/prompts-overview:grid-cols-3 @7xl/prompts-overview:grid-cols-5 gap-3">
            {Array.from({ length: KPI_CARDS }, (_, index) => (
                <LemonCard key={index} hoverEffect={false} className="p-3 flex flex-col gap-2 min-w-0">
                    <LemonSkeleton className="h-3 w-24" />
                    <LemonSkeleton className="h-7 w-16" />
                </LemonCard>
            ))}
        </div>
        <TileSkeleton title="Cited as a source over time" bodyClassName="h-64 w-full" />
        <div className="grid grid-cols-1 @3xl/prompts-overview:grid-cols-2 gap-4">
            <TileSkeleton title="Mentions by topic" bodyClassName="h-48 w-full" />
            <TileSkeleton title="Sites the engines cite most" bodyClassName="h-48 w-full" />
        </div>
        <TileSkeleton title="What the engines searched for" bodyClassName="h-48 w-full" />
    </section>
)
