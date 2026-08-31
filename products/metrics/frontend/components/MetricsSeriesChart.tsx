import { useValues } from 'kea'
import { useMemo } from 'react'

import {
    type Series,
    TimeSeriesBarChart,
    type TimeSeriesBarChartConfig,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
    createXAxisTickCallback,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import type { MetricsDisplaySettings } from '~/queries/schema/schema-general'

import { buildMetricsChartConfig, metricsBarValueDomain } from './metricsChartConfig'
import { MetricsExemplarMarkers, type MetricsExemplar } from './MetricsExemplarMarkers'
import { formatSeriesName, type MetricsChartSeries, seriesColor } from './metricsSeries'

const AREA_FILL_OPACITY = 0.2

/** Multi-series metric time-series chart, shared by the Viewer and the dashboard/insight tile. Every
 * series shares one time grid (the backend zero-fills), so the x-axis comes from the first series.
 *
 * `display.type: 'stat'` is in the schema but has no renderer yet, so it falls through to a line
 * chart rather than blanking the tile. */
export function MetricsSeriesChart({
    series,
    fallbackName,
    display,
    exemplars,
}: {
    series: MetricsChartSeries[]
    fallbackName: string
    display?: MetricsDisplaySettings
    exemplars?: MetricsExemplar[]
}): JSX.Element {
    const { timezone } = useValues(teamLogic)
    const theme = useChartTheme()
    const isBar = display?.type === 'bar'
    const isArea = display?.type === 'area'

    const chartSeries = useMemo<Series[]>(
        () =>
            series.map((s, index) => ({
                key: `${index}`,
                label: formatSeriesName({ labels: s.labels, metric_name: s.metricName ?? undefined }, fallbackName),
                // A null value is a gap (non-representable aggregate); charted as 0 for now.
                data: s.points.map((p) => p.value ?? 0),
                color: getColorVar(seriesColor(index)),
                ...(isArea ? { fill: { opacity: AREA_FILL_OPACITY } } : {}),
            })),
        [series, fallbackName, isArea]
    )
    const labels = useMemo(() => (series[0]?.points ?? []).map((p) => p.time), [series])

    const sharedConfig = useChartConfig<TimeSeriesLineChartConfig>(
        () =>
            buildMetricsChartConfig({
                display,
                xAxis: { tickFormatter: createXAxisTickCallback({ allDays: labels, timezone }) },
                seriesCount: chartSeries.length,
                labelFormatter: (label: string) => dayjs(label).tz(timezone).format('D MMM YYYY HH:mm:ss'),
            }),
        [labels, timezone, chartSeries.length, display]
    )

    const markers = exemplars?.length ? <MetricsExemplarMarkers exemplars={exemplars} /> : null

    return (
        <div className="relative flex h-full w-full min-h-0 flex-col">
            {isBar ? (
                <TimeSeriesBarChart
                    series={chartSeries}
                    labels={labels}
                    theme={theme}
                    config={{
                        ...(sharedConfig as TimeSeriesBarChartConfig),
                        // Bars read their bounds from `valueDomain`; `yAxis.min`/`max` are line-only.
                        valueDomain: metricsBarValueDomain(display?.yAxis),
                    }}
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
