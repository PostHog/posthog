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
import {
    extrapolatePartialValue,
    isExtrapolatable,
    type MetricsPartialBucketQuery,
    partialBucketFraction,
} from './metricsPartialBucket'
import type { MetricsPanelProps } from './registry'

const AREA_FILL_OPACITY = 0.2

/** Multi-series metric time-series chart (line / area / bar). Every series shares one time grid
 * (the backend zero-fills), so the x-axis comes from the first series.
 *
 * A null bucket is a gap (a non-representable aggregate). quill's `Series.data` is `number[]`
 * (no null), so a gap renders as 0 until quill takes null data; `display.nullMode` is read by
 * the chart config only, not here.
 *
 * A last bucket still in progress draws as a dashed segment. Counter series show it scaled up to
 * the full bucket, so the partial window does not read as a sudden drop. */
export function TimeSeriesPanel({
    series,
    display,
    fallbackName,
    exemplars,
    query,
}: MetricsPanelProps & { exemplars?: MetricsExemplar[]; query?: MetricsPartialBucketQuery }): JSX.Element {
    const { timezone } = useValues(teamLogic)
    const theme = useChartTheme()
    const isBar = display?.type === 'bar'
    const isArea = display?.type === 'area'

    const labels = useMemo(() => (series[0]?.points ?? []).map((p) => p.time), [series])
    const partialFraction = useMemo(
        () => (isBar ? null : partialBucketFraction(labels, query, timezone)),
        [labels, isBar, query, timezone]
    )

    const chartSeries = useMemo<Series[]>(() => {
        const names = formatSeriesNames(
            series.map((s) => ({ labels: s.labels, metric_name: s.metricName ?? undefined, clause: s.clause })),
            fallbackName
        )
        return series.map((s, index) => {
            const data = s.points.map((p) => p.value ?? 0)
            if (partialFraction !== null && isExtrapolatable(s, query)) {
                data[data.length - 1] = extrapolatePartialValue(data[data.length - 1], partialFraction)
            }
            return {
                key: `${index}`,
                label: names[index],
                data,
                color: getColorVar(seriesColor(index)),
                ...(isArea ? { fill: { opacity: AREA_FILL_OPACITY } } : {}),
                ...(partialFraction !== null ? { stroke: { partial: { fromIndex: data.length - 1 } } } : {}),
            }
        })
    }, [series, fallbackName, isArea, partialFraction, query])
    // `MetricsPanel` gives every series the same resolved unit, so the first series speaks for the chart.
    const unit = series[0]?.unit ?? undefined
    const plottedValues = useMemo(() => chartSeries.flatMap((s) => s.data), [chartSeries])

    const sharedConfig = useChartConfig<TimeSeriesLineChartConfig>(
        () =>
            buildMetricsChartConfig({
                display,
                xAxis: { timezone },
                seriesCount: chartSeries.length,
                labelFormatter: (label: string) => {
                    const formatted = dayjs(label).tz(timezone).format('D MMM YYYY HH:mm:ss')
                    return partialFraction !== null && label === labels[labels.length - 1]
                        ? `${formatted} (in progress)`
                        : formatted
                },
                unit,
                values: plottedValues,
            }),
        [timezone, chartSeries.length, display, unit, plottedValues, partialFraction, labels]
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
