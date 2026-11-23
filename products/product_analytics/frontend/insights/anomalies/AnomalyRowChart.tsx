import { useValues } from 'kea'
import { useMemo } from 'react'

import { type Series, TimeSeriesLineChart } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'lib/charts/chartErrorHandler'
import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { teamLogic } from 'scenes/teamLogic'

import type { AnomalySeriesApi } from 'products/signals/frontend/generated/api.schemas'

import { anomaliesTabLogic, anomalySeriesKey } from './anomaliesTabLogic'
import { AnomalyBucketShading } from './AnomalyBucketShading'
import { anomalyAxisTickFormatter, anomalyChartData } from './anomalyChartData'
import { ANOMALY_FILL_COLOR_VAR, EARLIER_ANOMALY_FILL_OPACITY } from './anomalyChartStyle'
import { AnomalyRangeStartLine } from './AnomalyRangeStartLine'

const handleChartError = makeChartErrorHandler('anomalies-tab-row-chart')

export interface AnomalyRowChartProps {
    series: AnomalySeriesApi
    // The flag window. The chart ends at the last checked bucket in it.
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
    const tickFormatter = useMemo(
        () => anomalyAxisTickFormatter(series.interval, timezone),
        [series.interval, timezone]
    )
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
                    xAxis: { timezone, interval: series.interval, tickFormatter },
                    xScale: 'time',
                    xDomain: data.xDomain,
                    yAxis: { tickFormatter: (value) => humanFriendlyNumber(value) },
                    showGrid: true,
                    tooltip: { valueFormatter: (value) => humanFriendlyNumber(value) },
                }}
                onError={handleChartError}
            >
                <AnomalyBucketShading
                    dataIndices={data.earlierFlaggedIndices}
                    color={getColorVar(ANOMALY_FILL_COLOR_VAR)}
                    opacity={EARLIER_ANOMALY_FILL_OPACITY}
                />
                <AnomalyBucketShading dataIndices={data.flaggedIndices} color={getColorVar(ANOMALY_FILL_COLOR_VAR)} />
                {data.flagWindowStartIndex != null && <AnomalyRangeStartLine dataIndex={data.flagWindowStartIndex} />}
            </TimeSeriesLineChart>
        </div>
    )
}
