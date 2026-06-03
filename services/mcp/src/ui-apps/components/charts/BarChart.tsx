import { type ReactElement, useMemo } from 'react'

import { TimeSeriesBarChart, type Series as QuillSeries, type TimeSeriesBarChartConfig } from '@posthog/quill-charts'

import { formatDate, formatNumber } from '../utils'
import { buildMcpChartTheme, ChartFrame } from './quillChart'

export interface DataPoint {
    x: number
    y: number
    label: string
}

export interface Series {
    label: string
    points: DataPoint[]
}

export interface BarChartProps {
    series: Series[]
    labels: string[]
    // Kept for call-site compatibility; Quill derives the y-axis domain from the data.
    maxValue: number
    showLegend?: boolean
    yAxisLabel?: string | undefined
}

export function BarChart({ series, labels, showLegend = true, yAxisLabel }: BarChartProps): ReactElement {
    const theme = useMemo(() => buildMcpChartTheme(), [])

    const quillSeries = useMemo<QuillSeries[]>(
        () =>
            series.map((s, i) => ({
                key: `${i}`,
                label: s.label,
                data: s.points.map((p) => p.y),
            })),
        [series]
    )

    const config = useMemo<TimeSeriesBarChartConfig>(
        () => ({
            barLayout: 'grouped',
            barCornerRadius: 2,
            xAxis: { tickFormatter: formatDate },
            yAxis: { tickFormatter: formatNumber, showGrid: true, ...(yAxisLabel ? { label: yAxisLabel } : {}) },
        }),
        [yAxisLabel]
    )

    return (
        <ChartFrame labels={series.map((s) => s.label)} colors={theme.colors} showLegend={showLegend}>
            <TimeSeriesBarChart series={quillSeries} labels={labels} theme={theme} config={config} />
        </ChartFrame>
    )
}
