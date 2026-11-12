import { LemonSkeleton } from '@posthog/lemon-ui'

import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'

import { ContentAutopilotTileSkeleton } from './ContentAutopilotTileSkeleton'

const KEYWORD_CHIPS = 5

/** The keywords layout while it loads, one placeholder per tile, so nothing moves when the keywords arrive. */
export const ContentAutopilotKeywordsSkeleton = (): JSX.Element => (
    <section className="flex flex-col gap-4" data-attr="content-autopilot-keywords-loading">
        <PagePerformanceCard className="min-w-0">
            <PagePerformanceCardHeader title="Keywords" />
            <div className="flex flex-col gap-3 p-3">
                <div className="flex flex-wrap gap-1">
                    {Array.from({ length: KEYWORD_CHIPS }, (_, index) => (
                        <LemonSkeleton key={index} className="h-6 w-24" />
                    ))}
                </div>
                <LemonSkeleton className="h-20 w-full" />
                <div className="flex items-center justify-between gap-2">
                    <LemonSkeleton className="h-4 w-80 max-w-full" />
                    <LemonSkeleton className="h-8 w-28" />
                </div>
            </div>
        </PagePerformanceCard>
        <ContentAutopilotTileSkeleton title="How your keywords perform" skeletonClassName="h-32 w-full" />
        <ContentAutopilotTileSkeleton title="What the engines add to your searches" skeletonClassName="h-32 w-full" />
    </section>
)
