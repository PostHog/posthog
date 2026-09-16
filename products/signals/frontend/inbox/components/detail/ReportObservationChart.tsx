import { useValues } from 'kea'
import { useMemo } from 'react'

import { TimeSeriesBarChart, TimeSeriesLineChart } from '@posthog/quill-charts'
import type { Series, TimeSeriesBarChartConfig, TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { teamLogic } from 'scenes/teamLogic'

import type { IntervalType } from '~/types'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import {
    formatReportMetricParts,
    formatReportMetricValue,
    type ReportMetricChartType,
    type ReportMetricSeriesPoints,
} from '../../utils/reportMetrics'

// Only the top is pinned: the sides keep the computed gutter so the first and last date labels fit.
// The top gridline sits at the top of the plot, and its tick label is centered on it, so the plot
// starts far enough down for the upper half of that label to stay inside the chart box.
const BAR_MARGINS = { top: 9 }

/** Height of the chart. A month of daily buckets needs this much room for the bar heights to
 *  separate and for the date row to stay smaller than the plot. The skeleton that stands in while
 *  the series loads reserves the same height, so the card does not resize when the data lands. */
export const OBSERVATION_CHART_HEIGHT_CLASS = 'h-36'

// Each labeled gridline already marks its own value, so the y baseline and the tick marks would
// state the scale a second time. A card this narrow cannot spend width on that.
const AXIS_CHROME = { showGrid: true, showAxisLines: { x: true, y: false }, showTickMarks: false } as const

/**
 * The observation's trend over its window: formatted values on the left, dates along the bottom, and
 * exact values in the tooltip. Bars for buckets that add up, a line for buckets that are levels;
 * `reportMetricChartType` decides which.
 */
export function ReportObservationChart({
    metric,
    points,
    type,
    interval,
}: {
    metric: ReportMetricApi
    points: ReportMetricSeriesPoints
    type: ReportMetricChartType
    interval: IntervalType | null | undefined
}): JSX.Element {
    const theme = useChartTheme()
    const { timezone } = useValues(teamLogic)

    const series = useMemo<Series[]>(
        () => [{ key: metric.metric_id, label: metric.title, data: points.values }],
        [metric.metric_id, metric.title, points.values]
    )
    const valueFormatter = useMemo(
        () => (value: number) => formatReportMetricValue(metric, value) ?? String(value),
        [metric]
    )
    const yAxisValueFormatter = useMemo(
        () => (value: number) => {
            if (metric.value_format === 'count' && !Number.isInteger(value)) {
                return ''
            }
            return formatReportMetricParts(metric, value)?.value ?? String(value)
        },
        [metric]
    )
    const xAxis = useMemo(() => ({ timezone, interval: interval ?? 'day' }), [timezone, interval])

    const lineConfig = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            xAxis,
            // Rates and durations emphasize change, so the value axis floats to the observed range.
            yAxis: { startAtZero: false, tickFormatter: yAxisValueFormatter },
            ...AXIS_CHROME,
            showCrosshair: true,
            tooltip: { pinnable: false, valueFormatter },
        }),
        [xAxis, yAxisValueFormatter, valueFormatter]
    )
    const barConfig = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            xAxis,
            yAxis: { tickFormatter: yAxisValueFormatter },
            ...AXIS_CHROME,
            showCrosshair: false,
            barCornerRadius: 1,
            bandPadding: 0.25,
            minBarSize: 2,
            margins: BAR_MARGINS,
            tooltip: { pinnable: false, hitArea: 'band', valueFormatter },
        }),
        [xAxis, yAxisValueFormatter, valueFormatter]
    )

    return (
        <div
            className={`flex ${OBSERVATION_CHART_HEIGHT_CLASS} w-full min-w-0 flex-col overflow-hidden`}
            data-attr="report-primary-metric-chart"
            data-chart-type={type}
        >
            {type === 'bar' ? (
                <TimeSeriesBarChart series={series} labels={points.labels} theme={theme} config={barConfig} />
            ) : (
                <TimeSeriesLineChart series={series} labels={points.labels} theme={theme} config={lineConfig} />
            )}
        </div>
    )
}
