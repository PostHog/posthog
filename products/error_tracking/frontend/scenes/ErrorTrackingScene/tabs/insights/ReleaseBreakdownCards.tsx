import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { useChartTheme } from 'lib/charts/hooks'

import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'
import { ExceptionBreakdownCard } from './ExceptionBreakdownCard'
import { buildAppBreakdown, buildReleaseBreakdown } from './releaseBreakdown'

export function ReleaseBreakdownCards(): JSX.Element {
    const { releaseRows, releaseRowsLoading, appRows, appRowsLoading, bucketKeys, interval, timezone, incompleteTail } =
        useValues(errorTrackingInsightsLogic)
    const { filterByBand } = useActions(errorTrackingInsightsLogic)
    const theme = useChartTheme()

    const releases = useMemo(
        () => buildReleaseBreakdown(releaseRows, bucketKeys, theme.colors),
        [releaseRows, bucketKeys, theme.colors]
    )
    // Folded from its own query rather than from the release rows: those are capped, so past the cap
    // an app would lose the releases that were dropped and report a total short of its real one.
    const apps = useMemo(
        () => buildAppBreakdown(appRows, bucketKeys, theme.colors),
        [appRows, bucketKeys, theme.colors]
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
                    incompleteTail={incompleteTail}
                    onSelectBand={filterByBand}
                />
                <ExceptionBreakdownCard
                    title="Exceptions by app"
                    breakdown={apps}
                    countNoun="app"
                    columnLabel="App"
                    labels={bucketKeys}
                    loading={appRowsLoading}
                    theme={theme}
                    timezone={timezone}
                    interval={interval}
                    incompleteTail={incompleteTail}
                    onSelectBand={filterByBand}
                />
            </div>
        </div>
    )
}
