import { useValues } from 'kea'

import { ChartCard } from './ChartCard'
import { ErrorsByPage } from './ErrorsByPage'
import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'
import { InsightsFilters } from './InsightsFilters'
import { SessionEndingIssues } from './SessionEndingIssues'
import { SummaryStats } from './SummaryStats'

export function ErrorTrackingInsights(): JSX.Element {
    const { exceptionVolumeQuery, affectedUsersRateQuery, crashFreeSessionsQuery, errorsByLocationQuery } =
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

            <ChartCard
                title="Errors by location"
                description="% of sessions with an exception by country"
                query={errorsByLocationQuery}
                chartKey="errors_by_location"
            />

            <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
                <SessionEndingIssues />
                <ErrorsByPage />
            </div>
        </div>
    )
}
