import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonDivider } from '@posthog/lemon-ui'

import { ChartCard } from './ChartCard'
import { InsightsFilters } from './InsightsFilters'
import { SummaryStats } from './SummaryStats'
import { TimeRangeControls } from './TimeRangeControls'
import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'
import { buildCrashFreeSessionsQuery, buildExceptionVolumeQuery } from './queries'

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
                <LemonDivider className="my-0" />
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
