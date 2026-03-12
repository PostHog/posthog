import { useValues } from 'kea'

import { ChartCard } from './ChartCard'
import { ErrorsByFeatureFlag } from './ErrorsByFeatureFlag'
import { ErrorsByPage } from './ErrorsByPage'
import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'
import { InsightsFilters } from './InsightsFilters'
import { SessionEndingIssues } from './SessionEndingIssues'
import { SummaryStats } from './SummaryStats'

export function ErrorTrackingInsights(): JSX.Element {
    const { exceptionVolumeQuery, affectedUsersRateQuery, crashFreeSessionsQuery } =
        useValues(errorTrackingInsightsLogic)

    return (
        <div className="space-y-4">
            <div className="border rounded bg-surface-primary p-2 space-y-2">
                <InsightsFilters />
            </div>
            <SummaryStats />

            <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
                <ChartCard
                    title="Exception volume"
                    description="Exceptions per day"
                    query={exceptionVolumeQuery}
                    chartKey="exception_volume"
                />
                <ChartCard
                    title="Affected users rate"
                    description="Percentage of users experiencing exceptions"
                    query={affectedUsersRateQuery}
                    chartKey="affected_users_rate"
                />
                <ChartCard
                    title="Crash-free sessions"
                    description="Percentage of sessions without any exceptions"
                    query={crashFreeSessionsQuery}
                    chartKey="crash_free_sessions"
                />
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
                <SessionEndingIssues />
                <ErrorsByPage />
                <ErrorsByFeatureFlag />
            </div>
        </div>
    )
}
