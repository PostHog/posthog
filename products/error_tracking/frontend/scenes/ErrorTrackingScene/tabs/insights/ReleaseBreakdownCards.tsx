import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { useChartTheme } from 'lib/charts/hooks'

import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'
import { ExceptionBreakdownCard } from './ExceptionBreakdownCard'
import { buildAppBreakdown, buildReleaseBreakdown } from './releaseBreakdown'

export function ReleaseBreakdownCards(): JSX.Element {
    const { releaseRows, releaseRowsLoading, bucketKeys, interval, timezone } = useValues(errorTrackingInsightsLogic)
    const { filterByBand } = useActions(errorTrackingInsightsLogic)
    const theme = useChartTheme()

    // Both panels fold the same rows, so the two can never disagree about the period's totals.
    const releases = useMemo(
        () => buildReleaseBreakdown(releaseRows, bucketKeys, theme.colors),
        [releaseRows, bucketKeys, theme.colors]
    )
    const apps = useMemo(
        () => buildAppBreakdown(releaseRows, bucketKeys, theme.colors),
        [releaseRows, bucketKeys, theme.colors]
    )

    // A chart and a table side by side need real width, and the nav sidebar plus an open side panel
    // take most of a laptop window. Break on the section's own width so the pair stacks whenever the
    // space actually ran out.
    return (
        <div className="@container">
            <div className="grid grid-cols-1 gap-4 @4xl:grid-cols-2">
                <ExceptionBreakdownCard
                    title="Exceptions by release"
                    breakdown={releases}
                    countNoun="release"
                    columnLabel="Release"
                    labels={bucketKeys}
                    loading={releaseRowsLoading}
                    theme={theme}
                    timezone={timezone}
                    interval={interval}
                    onSelectBand={filterByBand}
                />
                <ExceptionBreakdownCard
                    title="Exceptions by app"
                    breakdown={apps}
                    countNoun="app"
                    columnLabel="App"
                    labels={bucketKeys}
                    loading={releaseRowsLoading}
                    theme={theme}
                    timezone={timezone}
                    interval={interval}
                    onSelectBand={filterByBand}
                />
            </div>
        </div>
    )
}
