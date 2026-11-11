import { LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'

const KPI_CARDS = 5

const TileSkeleton = ({
    title,
    bodyClassName,
    skeletonClassName = 'h-full w-full',
    withInsightButton = false,
    withFooter = false,
}: {
    title: string
    bodyClassName: string
    skeletonClassName?: string
    withInsightButton?: boolean
    withFooter?: boolean
}): JSX.Element => (
    <PagePerformanceCard
        className="min-w-0"
        footer={withFooter ? <LemonSkeleton className="h-4 w-64 max-w-full" /> : undefined}
    >
        <PagePerformanceCardHeader
            title={title}
            // The loaded query tiles put a small "Open as insight" LemonButton here, which sets the header height.
            actions={withInsightButton ? <LemonSkeleton className="h-[2.0625rem] w-[2.0625rem]" /> : undefined}
        />
        <div className={bodyClassName}>
            <LemonSkeleton className={skeletonClassName} />
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
                <LemonCard key={index} hoverEffect={false} className="p-3 flex flex-col gap-1 min-w-0">
                    <LemonSkeleton className="h-4 w-24" />
                    <LemonSkeleton className="h-8 w-16" />
                    <LemonSkeleton className="h-4 w-20" />
                </LemonCard>
            ))}
        </div>
        <TileSkeleton title="Cited as a source over time" bodyClassName="h-72 p-2" withInsightButton withFooter />
        <div className="grid grid-cols-1 @3xl/prompts-overview:grid-cols-2 gap-4">
            <TileSkeleton title="Mentions by topic" bodyClassName="p-3" skeletonClassName="h-48 w-full" />
            <TileSkeleton
                title="Sites the engines cite most"
                bodyClassName="p-3"
                skeletonClassName="h-48 w-full"
                withInsightButton
                withFooter
            />
        </div>
        <TileSkeleton title="What the engines searched for" bodyClassName="p-3" skeletonClassName="h-48 w-full" />
    </section>
)
