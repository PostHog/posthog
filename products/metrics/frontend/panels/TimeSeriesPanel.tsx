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
 * Null buckets are gaps. quill's `Series.data` is `number[]` (no null), so the gap policy is:
 *  - `gap` / `connect`: render as a gap when quill supports it, else fall back to 0 (see note).
 *  - `zero`: render as 0.
 * The full `gap` draw (breaking the path) lands with the quill null-data change; until then a
 * null renders as 0 for `gap`/`connect` too, which matches the pre-existing behavior. */
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
    const nullMode = display?.nullMode ?? 'gap'

    const chartSeries = useMemo<Series[]>(() => {
        const names = formatSeriesNames(
            series.map((s) => ({ labels: s.labels, metric_name: s.metricName ?? undefined, clause: s.clause })),
            fallbackName
        )
        return series.map((s, index) => ({
            key: `${index}`,
            label: names[index],
            // A null value is a gap (non-representable aggregate). quill draws only numbers, so a
            // gap collapses to 0 here until quill takes null data; `zero` mode is explicit about it.
            data: s.points.map((p) => p.value ?? 0),
            color: getColorVar(seriesColor(index)),
            ...(isArea ? { fill: { opacity: AREA_FILL_OPACITY } } : {}),
        }))
        // nullMode currently only documents intent; the quill null-data change makes it live.
    }, [series, fallbackName, isArea, nullMode])
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
