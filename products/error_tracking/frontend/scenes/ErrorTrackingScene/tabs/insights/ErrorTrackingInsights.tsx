import { useValues } from 'kea'

import { ChartCard } from './ChartCard'
import { ErrorsByBrowser } from './ErrorsByBrowser'
import { ErrorsByPage } from './ErrorsByPage'
import { ErrorsNewVsReturning } from './ErrorsNewVsReturning'
import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'
import { InsightsFilters } from './InsightsFilters'
import { SessionEndingErrors } from './SessionEndingErrors'
import { SummaryStats } from './SummaryStats'
import { TopSessionsByErrors } from './TopSessionsByErrors'
import { TopUsersByErrors } from './TopUsersByErrors'

export function ErrorTrackingInsights(): JSX.Element {
    const { exceptionVolumeQuery, affectedUsersQuery, crashFreeSessionsQuery } = useValues(errorTrackingInsightsLogic)

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
                    title="Affected users"
                    description="Unique users experiencing exceptions"
                    query={affectedUsersQuery}
                    chartKey="affected_users"
                />
                <ChartCard
                    title="Crash-free sessions"
                    description="Percentage of sessions without any exceptions"
                    query={crashFreeSessionsQuery}
                    chartKey="crash_free_sessions"
                />
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
                <SessionEndingErrors />
                <TopUsersByErrors />
                <TopSessionsByErrors />
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
                <ErrorsByPage />
                <ErrorsByBrowser />
                <ErrorsNewVsReturning />
            </div>
        </div>
    )
}
