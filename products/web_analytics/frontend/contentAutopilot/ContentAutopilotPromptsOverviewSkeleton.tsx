import { LemonSkeleton } from '@posthog/lemon-ui'

import { ContentAutopilotStatStrip } from './ContentAutopilotStatStrip'
import { ContentAutopilotTileSkeleton } from './ContentAutopilotTileSkeleton'

const KPI_CARDS = 4

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
        <ContentAutopilotStatStrip
            className="grid-cols-2 @3xl/prompts-overview:grid-cols-4"
            data-attr="content-autopilot-prompts-overview-kpis-loading"
        >
            {Array.from({ length: KPI_CARDS }, (_, index) => (
                <div key={index} className="p-3 flex flex-col gap-1 min-w-0">
                    <LemonSkeleton className="h-4 w-24" />
                    <LemonSkeleton className="h-8 w-16" />
                    <LemonSkeleton className="h-4 w-20" />
                </div>
            ))}
        </ContentAutopilotStatStrip>
        <ContentAutopilotTileSkeleton
            title="Share of answers that cite you"
            bodyClassName="h-72 p-2"
            withInsightButton
        />
        <div className="grid grid-cols-1 @3xl/prompts-overview:grid-cols-2 gap-4">
            <ContentAutopilotTileSkeleton title="By engine" />
            <ContentAutopilotTileSkeleton title="Sites the engines cite most" withInsightButton />
        </div>
        <div className="grid grid-cols-1 @3xl/prompts-overview:grid-cols-2 gap-4">
            <ContentAutopilotTileSkeleton
                title="Topics at a glance"
                bodyClassName="h-72 p-2"
                skeletonClassName="h-full w-full"
            />
            <ContentAutopilotTileSkeleton title="Mentions by topic" />
        </div>
        <ContentAutopilotTileSkeleton title="What the engines searched for" />
    </section>
)
