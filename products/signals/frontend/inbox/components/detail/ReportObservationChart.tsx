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
const BAR_MARGINS = { top: 2 }

/**
 * The observation's trend over its window, drawn as a compact chart rather than a full insight:
 * formatted values on the left, dates along the bottom, and exact values in the tooltip. Bars for
 * buckets that add up, a line for buckets that are levels; `reportMetricChartType` decides which.
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
            showGrid: false,
            showAxisLines: { x: true, y: true },
            showTickMarks: true,
            showCrosshair: true,
            tooltip: { pinnable: false, valueFormatter },
        }),
        [xAxis, yAxisValueFormatter, valueFormatter]
    )
    const barConfig = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            xAxis,
            yAxis: { tickFormatter: yAxisValueFormatter },
            showGrid: false,
            showAxisLines: { x: true, y: true },
            showTickMarks: true,
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
            className="flex h-20 w-full min-w-0 flex-col overflow-hidden"
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
