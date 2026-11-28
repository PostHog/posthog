import { Skeleton } from '@posthog/quill'

import { ContentAutopilotStatStrip } from './ContentAutopilotStatStrip'
import { ContentAutopilotTileSkeleton } from './ContentAutopilotTileSkeleton'

const KPI_CARDS = 4
const TABS = 4

/** A brand's page while it loads, laid out like the loaded page, so nothing moves when the numbers arrive. */
export const ContentAutopilotBrandDetailSkeleton = (): JSX.Element => (
    <div className="@container/brand-page flex flex-col gap-4" data-attr="content-autopilot-brand-detail-loading">
        <div className="flex items-center gap-2">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-5 w-20" />
        </div>
        <ContentAutopilotStatStrip
            className="grid-cols-2 @3xl/brand-page:grid-cols-4"
            data-attr="content-autopilot-brand-kpis-loading"
        >
            {Array.from({ length: KPI_CARDS }, (_, index) => (
                <div key={index} className="flex min-w-0 flex-col gap-1 p-3">
                    <Skeleton className="h-4 w-24" />
                    <Skeleton className="h-8 w-16" />
                    <Skeleton className="h-4 w-20" />
                </div>
            ))}
        </ContentAutopilotStatStrip>
        <div className="flex gap-4 border-b pb-2">
            {Array.from({ length: TABS }, (_, index) => (
                <Skeleton key={index} className="h-5 w-16" />
            ))}
        </div>
        <ContentAutopilotTileSkeleton title="Prompts that name the brand" />
    </div>
)
