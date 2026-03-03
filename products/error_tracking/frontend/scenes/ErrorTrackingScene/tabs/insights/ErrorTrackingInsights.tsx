import { BindLogic, useValues } from 'kea'

import { issueFiltersLogic } from 'products/error_tracking/frontend/components/IssueFilters/issueFiltersLogic'

import { ChartCard } from './ChartCard'
import { errorTrackingInsightsLogic, INSIGHTS_LOGIC_KEY } from './errorTrackingInsightsLogic'
import { InsightsFilters } from './InsightsFilters'
import { SummaryStats } from './SummaryStats'

export function ErrorTrackingInsights(): JSX.Element {
    return (
        <BindLogic logic={issueFiltersLogic} props={{ logicKey: INSIGHTS_LOGIC_KEY }}>
            <InsightsContent />
        </BindLogic>
    )
}

function InsightsContent(): JSX.Element {
    const { exceptionVolumeQuery, crashFreeSessionsQuery } = useValues(errorTrackingInsightsLogic)

    return (
        <div className="space-y-4">
            <div className="border rounded bg-surface-primary p-2 space-y-2">
                <InsightsFilters />
            </div>
            <SummaryStats />

            <div className="border rounded bg-surface-primary overflow-hidden">
                <div className="px-3 py-2 border-b text-xs font-semibold uppercase tracking-wide text-secondary">
                    Charts
                </div>
                <div className="p-3 grid grid-cols-1 xl:grid-cols-2 gap-3">
                    <ChartCard
                        title="Exception volume"
                        description="Exceptions per day"
                        query={exceptionVolumeQuery}
                        chartKey="exception_volume"
                    />
                    <ChartCard
                        title="Crash-free sessions"
                        description="Percentage of sessions without any exceptions"
                        query={crashFreeSessionsQuery}
                        chartKey="crash_free_sessions"
                    />
                </div>
            </div>
        </div>
    )
}
