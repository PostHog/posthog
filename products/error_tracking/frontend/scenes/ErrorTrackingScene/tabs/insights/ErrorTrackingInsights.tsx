import { BindLogic, useValues } from 'kea'
import { useMemo } from 'react'

import { issueFiltersLogic } from 'products/error_tracking/frontend/components/IssueFilters/issueFiltersLogic'

import { ChartCard } from './ChartCard'
import { errorTrackingInsightsLogic, INSIGHTS_LOGIC_KEY } from './errorTrackingInsightsLogic'
import { InsightsFilters } from './InsightsFilters'
import { buildCrashFreeSessionsQuery, buildExceptionVolumeQuery } from './queries'
import { SummaryStats } from './SummaryStats'

export function ErrorTrackingInsights(): JSX.Element {
    return (
        <BindLogic logic={issueFiltersLogic} props={{ logicKey: INSIGHTS_LOGIC_KEY }}>
            <InsightsContent />
        </BindLogic>
    )
}

function InsightsContent(): JSX.Element {
    const { dateRange, mergedFilterGroup, filterTestAccounts, refreshKey } = useValues(errorTrackingInsightsLogic)

    const filters = useMemo(
        () => ({ filterGroup: mergedFilterGroup, filterTestAccounts }),
        [mergedFilterGroup, filterTestAccounts]
    )

    const exceptionVolumeQuery = useMemo(
        () => buildExceptionVolumeQuery(dateRange.date_from ?? '-7d', dateRange.date_to ?? null, filters),
        [dateRange, filters]
    )
    const crashFreeQuery = useMemo(
        () => buildCrashFreeSessionsQuery(dateRange.date_from ?? '-7d', dateRange.date_to ?? null, filters),
        [dateRange, filters]
    )

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
                        refreshKey={refreshKey}
                    />
                    <ChartCard
                        title="Crash-free sessions"
                        description="Percentage of sessions without any exceptions"
                        query={crashFreeQuery}
                        chartKey="crash_free_sessions"
                        refreshKey={refreshKey}
                    />
                </div>
            </div>
        </div>
    )
}
