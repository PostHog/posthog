import { useValues } from 'kea'
import { useMemo } from 'react'

import {
    type Series,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
    createXAxisTickCallback,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { MetricsExemplarMarkers, type MetricsExemplar } from './MetricsExemplarMarkers'
import { formatSeriesName, type MetricsChartSeries, seriesColor } from './metricsSeries'

/** Multi-series metric line chart, shared by the Viewer and the dashboard/insight tile. Every series
 * shares one time grid (the backend zero-fills), so the x-axis comes from the first series. */
export function MetricsSeriesChart({
    series,
    fallbackName,
    exemplars,
}: {
    series: MetricsChartSeries[]
    fallbackName: string
    exemplars?: MetricsExemplar[]
}): JSX.Element {
    const { timezone } = useValues(teamLogic)
    const theme = useChartTheme()

    const chartSeries = useMemo<Series[]>(
        () =>
            series.map((s, index) => ({
                key: `${index}`,
                label: formatSeriesName({ labels: s.labels, metric_name: s.metricName ?? undefined }, fallbackName),
                // A null value is a gap (non-representable aggregate); charted as 0 for now.
                data: s.points.map((p) => p.value ?? 0),
                color: getColorVar(seriesColor(index)),
            })),
        [series, fallbackName]
    )
    const labels = useMemo(() => (series[0]?.points ?? []).map((p) => p.time), [series])

    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            xAxis: { tickFormatter: createXAxisTickCallback({ allDays: labels, timezone }) },
            legend: { show: chartSeries.length > 1, interactive: true },
            tooltip: {
                placement: 'cursor',
                pinnable: true,
                labelFormatter: (label: string) => dayjs(label).tz(timezone).format('D MMM YYYY HH:mm:ss'),
            },
        }),
        [labels, timezone, chartSeries.length]
    )

    return (
        <div className="relative flex h-full w-full min-h-0 flex-col">
            <TimeSeriesLineChart series={chartSeries} labels={labels} theme={theme} config={config}>
                {exemplars?.length ? <MetricsExemplarMarkers exemplars={exemplars} /> : null}
            </TimeSeriesLineChart>
        </div>
    )
}
