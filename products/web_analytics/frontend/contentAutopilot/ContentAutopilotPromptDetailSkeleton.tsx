import { Skeleton } from '@posthog/quill'

import { ContentAutopilotStatStrip } from './ContentAutopilotStatStrip'
import { ContentAutopilotTileSkeleton } from './ContentAutopilotTileSkeleton'

const KPI_CARDS = 3
const REPORT_TABS = 6

/** A prompt's report while it loads, laid out like its Overview tab, so nothing moves when the numbers arrive. */
export const ContentAutopilotPromptDetailSkeleton = (): JSX.Element => (
    <div className="@container/prompt-report flex flex-col gap-4" data-attr="content-autopilot-prompt-report-loading">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <Skeleton className="h-5 w-20" />
            <Skeleton className="h-5 w-20" />
            <Skeleton className="h-5 w-16" />
            <Skeleton className="h-4 w-40" />
        </div>
        <ContentAutopilotStatStrip
            className="grid-cols-1 @2xl/prompt-report:grid-cols-3"
            data-attr="content-autopilot-prompt-kpis-loading"
        >
            {Array.from({ length: KPI_CARDS }, (_, index) => (
                <div key={index} className="p-3 flex flex-col gap-1 min-w-0">
                    <Skeleton className="h-4 w-32" />
                    <Skeleton className="h-8 w-16" />
                    <Skeleton className="h-4 w-24" />
                </div>
            ))}
        </ContentAutopilotStatStrip>
        <div className="flex gap-4 border-b pb-2">
            {Array.from({ length: REPORT_TABS }, (_, index) => (
                <Skeleton key={index} className="h-5 w-16" />
            ))}
        </div>
        <ContentAutopilotTileSkeleton
            title="Answers that cite you"
            bodyClassName="h-72 p-2"
            skeletonClassName="h-full w-full"
            withInsightButton
        />
        <div className="grid grid-cols-1 @3xl/prompt-report:grid-cols-2 gap-4">
            <ContentAutopilotTileSkeleton title="By engine" skeletonClassName="h-32 w-full" />
            <ContentAutopilotTileSkeleton title="How the answers speak about you" skeletonClassName="h-32 w-full" />
        </div>
    </div>
)
