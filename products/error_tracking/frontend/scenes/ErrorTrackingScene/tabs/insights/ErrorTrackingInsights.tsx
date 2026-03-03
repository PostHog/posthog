import { useActions, useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { ChartCard } from './ChartCard'
import { errorTrackingInsightsLogic, InsightsTrackableItem } from './errorTrackingInsightsLogic'
import { InsightsFilters } from './InsightsFilters'
import { buildCrashFreeSessionsQuery, buildExceptionVolumeQuery } from './queries'
import { SummaryStats } from './SummaryStats'

export function ErrorTrackingInsights(): JSX.Element {
    const { dateRange, mergedFilterGroup, filterTestAccounts, loadStartTime, refreshKey } =
        useValues(errorTrackingInsightsLogic)
    const { reportItemLoaded } = useActions(errorTrackingInsightsLogic)

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

    const handleChartLoad = useCallback(
        (item: InsightsTrackableItem, durationMs: number) => reportItemLoaded(item, durationMs),
        [reportItemLoaded]
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
                        loadStartTime={loadStartTime}
                        onLoad={handleChartLoad}
                    />
                    <ChartCard
                        title="Crash-free sessions"
                        description="Percentage of sessions without any exceptions"
                        query={crashFreeQuery}
                        chartKey="crash_free_sessions"
                        refreshKey={refreshKey}
                        loadStartTime={loadStartTime}
                        onLoad={handleChartLoad}
                    />
                </div>
            </div>
        </div>
    )
}
