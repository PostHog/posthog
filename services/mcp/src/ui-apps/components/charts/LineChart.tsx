import { type ReactElement, useMemo } from 'react'

import { TimeSeriesLineChart, type Series as ChartSeries, type TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { formatDate, formatNumber } from '../utils'
import { buildMcpChartTheme, ChartFrame } from './shared'

export interface DataPoint {
    x: number
    y: number
    label: string
}

export interface Series {
    label: string
    points: DataPoint[]
}

export interface LineChartProps {
    series: Series[]
    labels: string[]
    // Kept for call-site compatibility; the chart derives the y-axis domain from the data.
    maxValue: number
    showLegend?: boolean
    yAxisLabel?: string | undefined
}

export function LineChart({ series, labels, showLegend = true, yAxisLabel }: LineChartProps): ReactElement {
    const theme = useMemo(() => buildMcpChartTheme(), [])

    const chartSeries = useMemo<ChartSeries[]>(
        () =>
            series.map((s, i) => ({
                key: `${i}`,
                label: s.label,
                data: s.points.map((p) => p.y),
                points: { radius: 3 },
            })),
        [series]
    )

    const config = useMemo<TimeSeriesLineChartConfig>(
        () => ({
            xAxis: { tickFormatter: formatDate },
            yAxis: { tickFormatter: formatNumber, showGrid: true, ...(yAxisLabel ? { label: yAxisLabel } : {}) },
        }),
        [yAxisLabel]
    )

    return (
        <ChartFrame labels={series.map((s) => s.label)} colors={theme.colors} showLegend={showLegend}>
            <TimeSeriesLineChart series={chartSeries} labels={labels} theme={theme} config={config} />
        </ChartFrame>
    )
}
