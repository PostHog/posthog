import { CoverageCard } from './CoverageCard'
import { FailureGroupsCard } from './FailureGroupsCard'
import { IntentThemesCard } from './IntentThemesCard'
import { MissingCard } from './MissingCard'
import { OverviewFilterBar } from './OverviewFilterBar'
import { OverviewSummaryCard } from './OverviewSummaryCard'
import { WhoCard } from './WhoCard'

/**
 * The landing tab: what people did with the server in this window, what stopped them, and
 * whether the instrumentation behind those answers is good enough to act on.
 */
export function MCPAnalyticsOverview(): JSX.Element {
    return (
        <div className="@container/mcp-overview flex min-w-0 flex-col gap-4" data-attr="mcp-analytics-overview">
            <OverviewFilterBar />
            <section className="flex min-w-0 flex-col gap-4" data-quill>
                <OverviewSummaryCard />
                <div className="grid min-w-0 grid-cols-1 items-start gap-4 @min-[56rem]/mcp-overview:grid-cols-3">
                    <div className="min-w-0 @min-[56rem]/mcp-overview:col-span-2">
                        <IntentThemesCard />
                    </div>
                    <div className="min-w-0">
                        <WhoCard />
                    </div>
                </div>
                <div className="grid min-w-0 grid-cols-1 items-start gap-4 @min-[56rem]/mcp-overview:grid-cols-3">
                    <div className="min-w-0 @min-[56rem]/mcp-overview:col-span-2">
                        <FailureGroupsCard />
                    </div>
                    <div className="min-w-0">
                        <MissingCard />
                    </div>
                </div>
                <CoverageCard />
            </section>
        </div>
    )
}
