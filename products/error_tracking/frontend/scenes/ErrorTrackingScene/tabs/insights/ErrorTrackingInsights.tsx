import { useValues } from 'kea'
import { useMemo } from 'react'

import { ChartCard } from './ChartCard'
import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'
import { InsightsFilters } from './InsightsFilters'
import { buildCrashFreeSessionsQuery, buildExceptionVolumeQuery } from './queries'
import { SummaryStats } from './SummaryStats'
import { TimeRangeControls } from './TimeRangeControls'

export function ErrorTrackingInsights(): JSX.Element {
    const { dateFrom, chartDateTo, filterGroup, filterTestAccounts } = useValues(errorTrackingInsightsLogic)

    const filters = useMemo(() => ({ filterGroup, filterTestAccounts }), [filterGroup, filterTestAccounts])

    const exceptionVolumeQuery = useMemo(
        () => buildExceptionVolumeQuery(dateFrom, chartDateTo, filters),
        [dateFrom, chartDateTo, filters]
    )
    const crashFreeQuery = useMemo(
        () => buildCrashFreeSessionsQuery(dateFrom, chartDateTo, filters),
        [dateFrom, chartDateTo, filters]
    )

    return (
        <div className="space-y-4">
            <div className="border rounded bg-surface-primary p-2 space-y-2">
                <TimeRangeControls />
                <InsightsFilters />
            </div>
            <SummaryStats />

            <div className="border rounded bg-surface-primary overflow-hidden">
                <div className="px-3 py-2 border-b text-xs font-semibold uppercase tracking-wide text-secondary">
                    Charts
                </div>
                <div className="p-3 grid grid-cols-1 xl:grid-cols-2 gap-3">
                    <ChartCard title="Exception volume" description="Exceptions per day" query={exceptionVolumeQuery} />
                    <ChartCard
                        title="Crash-free sessions"
                        description="Percentage of sessions without any exceptions"
                        query={crashFreeQuery}
                    />
                </div>
            </div>
        </div>
    )
}
