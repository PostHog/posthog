import { useValues } from 'kea'
import { useMemo } from 'react'

import {
    type Series,
    TimeSeriesBarChart,
    type TimeSeriesBarChartConfig,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { buildMetricsChartConfig } from '../components/metricsChartConfig'
import { MetricsExemplarMarkers, type MetricsExemplar } from '../components/MetricsExemplarMarkers'
import { formatSeriesNames, seriesColor } from '../components/metricsSeries'
import type { MetricsPanelProps } from './registry'

const AREA_FILL_OPACITY = 0.2

/** Multi-series metric time-series chart (line / area / bar). Every series shares one time grid
 * (the backend zero-fills), so the x-axis comes from the first series.
 *
 * A null bucket is a gap (a non-representable aggregate). quill's `Series.data` is `number[]`
 * (no null), so a gap renders as 0 until quill takes null data; `display.nullMode` is read by
 * the chart config only, not here. */
export function TimeSeriesPanel({
    series,
    display,
    fallbackName,
    exemplars,
}: MetricsPanelProps & { exemplars?: MetricsExemplar[] }): JSX.Element {
    const { timezone } = useValues(teamLogic)
    const theme = useChartTheme()
    const isBar = display?.type === 'bar'
    const isArea = display?.type === 'area'

    const chartSeries = useMemo<Series[]>(() => {
        const names = formatSeriesNames(
            series.map((s) => ({ labels: s.labels, metric_name: s.metricName ?? undefined, clause: s.clause })),
            fallbackName
        )
        return series.map((s, index) => ({
            key: `${index}`,
            label: names[index],
            data: s.points.map((p) => p.value ?? 0),
            color: getColorVar(seriesColor(index)),
            ...(isArea ? { fill: { opacity: AREA_FILL_OPACITY } } : {}),
        }))
    }, [series, fallbackName, isArea])
    const labels = useMemo(() => (series[0]?.points ?? []).map((p) => p.time), [series])

    const sharedConfig = useChartConfig<TimeSeriesLineChartConfig>(
        () =>
            buildMetricsChartConfig({
                display,
                xAxis: { timezone },
                seriesCount: chartSeries.length,
                labelFormatter: (label: string) => dayjs(label).tz(timezone).format('D MMM YYYY HH:mm:ss'),
            }),
        [timezone, chartSeries.length, display]
    )

    const markers = exemplars?.length ? <MetricsExemplarMarkers exemplars={exemplars} /> : null

    return (
        <div className="relative flex h-full w-full min-h-0 flex-col">
            {isBar ? (
                <TimeSeriesBarChart
                    series={chartSeries}
                    labels={labels}
                    theme={theme}
                    config={sharedConfig as TimeSeriesBarChartConfig}
                >
                    {markers}
                </TimeSeriesBarChart>
            ) : (
                <TimeSeriesLineChart series={chartSeries} labels={labels} theme={theme} config={sharedConfig}>
                    {markers}
                </TimeSeriesLineChart>
            )}
        </div>
    )
}
