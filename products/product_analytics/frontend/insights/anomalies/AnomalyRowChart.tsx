import { useValues } from 'kea'
import { useMemo } from 'react'

import { HighlightedRange, type Series, TimeSeriesLineChart } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'lib/charts/chartErrorHandler'
import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { teamLogic } from 'scenes/teamLogic'

import type { AnomalySeriesApi } from 'products/signals/frontend/generated/api.schemas'

import { anomaliesTabLogic, anomalySeriesKey } from './anomaliesTabLogic'
import { AnomalyBucketShading } from './AnomalyBucketShading'
import { anomalyChartData } from './anomalyChartData'

const handleChartError = makeChartErrorHandler('anomalies-tab-row-chart')

const FLAG_WINDOW_OPACITY = 0.1
// Flags before the flag window did not put the series in the list, so they draw fainter.
const EARLIER_FLAG_OPACITY = 0.08

export interface AnomalyRowChartProps {
    series: AnomalySeriesApi
    // The flag window, which ends at the right edge of the chart.
    dateFrom: string
    dateTo: string
}

export function AnomalyRowChart({ series, dateFrom, dateTo }: AnomalyRowChartProps): JSX.Element {
    const theme = useChartTheme()
    const { timezone } = useValues(teamLogic)
    const { chartPoints, chartPointsStatus } = useValues(anomaliesTabLogic)
    const id = anomalySeriesKey(series)
    const loaded = chartPoints[id]

    const data = useMemo(
        () =>
            loaded
                ? anomalyChartData(
                      series,
                      loaded.points,
                      { chartFrom: loaded.chartFrom, flagFrom: dateFrom, dateTo },
                      timezone
                  )
                : null,
        [series, loaded, dateFrom, dateTo, timezone]
    )
    const flagWindowIndices = useMemo(() => {
        const start = data?.flagWindowStartIndex
        return data && start != null
            ? Array.from({ length: data.labels.length - start }, (_, index) => start + index)
            : []
    }, [data])
    const chartSeries = useMemo<Series[]>(
        () => (data ? [{ key: series.series_key, label: series.series_label || 'Value', data: data.values }] : []),
        [data, series.series_key, series.series_label]
    )
    if (!loaded) {
        return chartPointsStatus[id] === 'failed' ? (
            <div className="h-28 flex items-center justify-center text-secondary text-sm">
                Couldn't load this chart. Refresh the page to try again.
            </div>
        ) : (
            <LemonSkeleton className="h-28 w-full" />
        )
    }
    if (!data) {
        return (
            <div className="h-28 flex items-center justify-center text-secondary text-sm">
                No scored values to chart
            </div>
        )
    }

    return (
        <div className="h-28 flex flex-col" data-attr="anomalies-tab-row-chart">
            <TimeSeriesLineChart
                series={chartSeries}
                labels={data.labels}
                theme={theme}
                config={{
                    xAxis: { timezone, interval: series.interval },
                    yAxis: { tickFormatter: (value) => humanFriendlyNumber(value) },
                    showGrid: true,
                    tooltip: { valueFormatter: (value) => humanFriendlyNumber(value) },
                }}
                onError={handleChartError}
            >
                <AnomalyBucketShading
                    dataIndices={flagWindowIndices}
                    color={getColorVar('muted')}
                    opacity={FLAG_WINDOW_OPACITY}
                />
                <AnomalyBucketShading
                    dataIndices={data.earlierFlaggedIndices}
                    color={getColorVar('danger')}
                    opacity={EARLIER_FLAG_OPACITY}
                />
                <AnomalyBucketShading dataIndices={data.flaggedIndices} color={getColorVar('danger')} />
                {data.firstUncheckedIndex != null && (
                    <HighlightedRange
                        // From the last checked bucket, so a single unchecked bucket still shows as a band.
                        start={Math.max(0, data.firstUncheckedIndex - 1)}
                        end={data.labels.length - 1}
                        fillOpacity={0.15}
                        borderOpacity={0}
                    />
                )}
            </TimeSeriesLineChart>
        </div>
    )
}
