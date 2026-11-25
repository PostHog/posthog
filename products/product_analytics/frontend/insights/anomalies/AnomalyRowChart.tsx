import { useValues } from 'kea'
import { useMemo } from 'react'

import { type AnomalyMarker, AnomalyPointsLayer, type Series, TimeSeriesLineChart } from '@posthog/quill-charts'

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
import {
    ANOMALY_FILL_COLOR_VAR,
    ANOMALY_POINT_RADIUS,
    EARLIER_ANOMALY_FILL_OPACITY,
    earlierAnomalyPointColor,
} from './anomalyChartStyle'
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
    const labelCount = data?.labels.length ?? 0
    const tickFormatter = useMemo(
        () => anomalyAxisTickFormatter(series.interval, timezone, labelCount),
        [series.interval, timezone, labelCount]
    )
    const chartSeries = useMemo<Series[]>(
        () => (data ? [{ key: series.series_key, label: series.series_label || 'Value', data: data.values }] : []),
        [data, series.series_key, series.series_label]
    )
    const fillColor = getColorVar(ANOMALY_FILL_COLOR_VAR)
    const markers = useMemo<AnomalyMarker[]>(() => {
        if (!data) {
            return []
        }
        const marker = (dataIndex: number, color: string): AnomalyMarker => ({
            dataIndex,
            value: data.values[dataIndex],
            color,
            yAxisId: 'left',
        })
        // In-range points come last, so they draw on top where an earlier point overlaps them.
        return [
            ...data.earlierFlaggedIndices.map((index) => marker(index, earlierAnomalyPointColor(fillColor))),
            ...data.flaggedIndices.map((index) => marker(index, fillColor)),
        ]
    }, [data, fillColor])
    if (!loaded) {
        return chartPointsStatus[id] === 'failed' ? (
            <div className="h-44 flex items-center justify-center text-secondary text-sm">
                Couldn't load this chart. Refresh the page to try again.
            </div>
        ) : (
            <LemonSkeleton className="h-44 w-full" />
        )
    }
    if (!data) {
        return (
            <div className="h-44 flex items-center justify-center text-secondary text-sm">
                No scored values to chart
            </div>
        )
    }

    return (
        <div className="h-44 flex flex-col" data-attr="anomalies-tab-row-chart">
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
                    color={fillColor}
                    opacity={EARLIER_ANOMALY_FILL_OPACITY}
                />
                <AnomalyBucketShading dataIndices={data.flaggedIndices} color={fillColor} />
                {data.flagWindowStartIndex != null && <AnomalyRangeStartLine dataIndex={data.flagWindowStartIndex} />}
                <AnomalyPointsLayer markers={markers} radius={ANOMALY_POINT_RADIUS} />
            </TimeSeriesLineChart>
        </div>
    )
}
