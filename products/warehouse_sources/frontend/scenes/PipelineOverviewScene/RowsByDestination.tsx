import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'
import { TimeSeriesLineChart } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { teamLogic } from 'scenes/teamLogic'

import { pipelineOverviewSceneLogic } from './pipelineOverviewSceneLogic'

export function RowsByDestination(): JSX.Element {
    const { rowsByDestination, destinationRowSeries, destinationRowSeriesLoading, destinationsLoading, window } =
        useValues(pipelineOverviewSceneLogic)
    const { currentTeam } = useValues(teamLogic)
    const theme = useChartTheme()

    if ((destinationRowSeriesLoading && destinationRowSeries === null) || destinationsLoading) {
        return <LemonSkeleton className="h-64 w-full" />
    }

    if (rowsByDestination.length === 0) {
        return (
            <div className="rounded border border-primary bg-surface-primary px-4 py-6 text-center text-muted">
                No rows were written to a destination in this window.
            </div>
        )
    }

    return (
        // The chart fills its container, so it needs a definite height AND a flex column here.
        // Without both, the canvas resolves to zero height and draws nothing.
        <div className="flex h-80 flex-col overflow-hidden rounded border border-primary bg-surface-primary p-3">
            <TimeSeriesLineChart
                series={rowsByDestination}
                labels={destinationRowSeries?.labels ?? []}
                theme={theme}
                config={{
                    xAxis: {
                        timezone: currentTeam?.timezone ?? 'UTC',
                        interval: window === 1 ? 'hour' : 'day',
                    },
                    yAxis: { format: 'short' },
                    legend: { show: true, position: 'bottom' },
                    tooltip: { pinnable: true },
                }}
            />
        </div>
    )
}
