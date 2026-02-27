import { useValues } from 'kea'
import { useMemo } from 'react'

import { ChartCard } from './ChartCard'
import { SummaryStats } from './SummaryStats'
import { TimeRangeControls } from './TimeRangeControls'
import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'
import { buildCrashFreeSessionsQuery, buildExceptionVolumeQuery } from './queries'

export function ErrorTrackingInsights(): JSX.Element {
    const { dateFrom, chartDateTo } = useValues(errorTrackingInsightsLogic)

    const exceptionVolumeQuery = useMemo(
        () => buildExceptionVolumeQuery(dateFrom, chartDateTo),
        [dateFrom, chartDateTo]
    )
    const crashFreeQuery = useMemo(() => buildCrashFreeSessionsQuery(dateFrom, chartDateTo), [dateFrom, chartDateTo])

    return (
        <div className="space-y-4">
            <div className="border rounded bg-surface-primary p-2">
                <TimeRangeControls />
            </div>
            <SummaryStats />

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <ChartCard title="Exception volume" description="Exceptions per day" query={exceptionVolumeQuery} />
                <ChartCard
                    title="Crash-free sessions"
                    description="Percentage of sessions without any exceptions"
                    query={crashFreeQuery}
                />
            </div>
        </div>
    )
}
