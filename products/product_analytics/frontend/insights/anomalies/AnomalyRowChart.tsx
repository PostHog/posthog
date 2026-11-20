import { useValues } from 'kea'
import { useMemo } from 'react'

import { HighlightedRange, type Series, TimeSeriesLineChart } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'lib/charts/chartErrorHandler'
import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { teamLogic } from 'scenes/teamLogic'

import type { AnomalySeriesApi } from 'products/signals/frontend/generated/api.schemas'

import { AnomalyBucketShading } from './AnomalyBucketShading'
import { anomalyChartData } from './anomalyChartData'

const handleChartError = makeChartErrorHandler('anomalies-tab-row-chart')

export interface AnomalyRowChartProps {
    series: AnomalySeriesApi
    dateFrom: string
    dateTo: string
}

export function AnomalyRowChart({ series, dateFrom, dateTo }: AnomalyRowChartProps): JSX.Element {
    const theme = useChartTheme()
    const { timezone } = useValues(teamLogic)

    const data = useMemo(
        () => anomalyChartData(series, dateFrom, dateTo, timezone),
        [series, dateFrom, dateTo, timezone]
    )
    const chartSeries = useMemo<Series[]>(
        () => (data ? [{ key: series.series_key, label: series.series_label || 'Value', data: data.values }] : []),
        [data, series.series_key, series.series_label]
    )
    if (!data) {
        return (
            <div className="h-28 flex items-center justify-center text-secondary text-sm">
                No scored values to chart in this range
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
