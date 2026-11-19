import { LemonSkeleton } from '@posthog/lemon-ui'

import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'

/** A loading tile with its real title, so the page reads the same before and after its data arrives. */
export const ContentAutopilotTileSkeleton = ({
    title,
    bodyClassName = 'p-3',
    skeletonClassName = 'h-48 w-full',
    withInsightButton = false,
}: {
    title: string
    bodyClassName?: string
    skeletonClassName?: string
    withInsightButton?: boolean
}): JSX.Element => (
    <PagePerformanceCard className="min-w-0">
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
