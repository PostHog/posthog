import { Skeleton } from '@posthog/quill'

import { ContentAutopilotStatStrip } from './ContentAutopilotStatStrip'
import { ContentAutopilotTileSkeleton } from './ContentAutopilotTileSkeleton'

const KPI_CARDS = 4
const GRID_CLASS_NAME = 'grid grid-cols-1 @3xl/prompts-overview:grid-cols-2 gap-4'

/** The overview's layout while it loads, one placeholder per tile in the same order, so nothing moves when the
 *  numbers arrive. */
export const ContentAutopilotPromptsOverviewSkeleton = (): JSX.Element => (
    <section
        className="@container/prompts-overview flex flex-col gap-4"
        aria-busy
        data-attr="content-autopilot-prompts-overview-loading"
    >
        <ContentAutopilotStatStrip
            className="grid-cols-2 @3xl/prompts-overview:grid-cols-4"
            data-attr="content-autopilot-prompts-overview-kpis-loading"
        >
            {Array.from({ length: KPI_CARDS }, (_, index) => (
                <div key={index} className="flex min-w-0 flex-col gap-1 px-4 py-3">
                    <Skeleton className="h-5 w-24 max-w-full" />
                    <Skeleton className="h-8 w-16" />
                    <Skeleton className="h-4 w-20 max-w-full" />
                </div>
            ))}
        </ContentAutopilotStatStrip>
        <ContentAutopilotTileSkeleton title="Visibility" skeletonClassName="h-72 w-full" withInsightButton />
        <div className={GRID_CLASS_NAME}>
            <ContentAutopilotTileSkeleton title="Prompts that moved most" />
            <ContentAutopilotTileSkeleton title="Your pages that moved most" />
        </div>
        <div className={GRID_CLASS_NAME}>
            <ContentAutopilotTileSkeleton title="By engine" />
            <ContentAutopilotTileSkeleton title="Visibility by topic" />
        </div>
        <ContentAutopilotTileSkeleton title="Visibility by engine and topic" />
        <div className={GRID_CLASS_NAME}>
            <ContentAutopilotTileSkeleton title="Sites the engines cite most" withInsightButton />
            <ContentAutopilotTileSkeleton title="What the engines searched for" />
        </div>
    </section>
)
