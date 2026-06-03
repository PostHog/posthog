import { type ReactElement, useMemo } from 'react'

import { TimeSeriesLineChart, type Series as QuillSeries, type TimeSeriesLineChartConfig } from '@posthog/quill-charts'

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

export interface LineChartProps {
    series: Series[]
    labels: string[]
    // Kept for call-site compatibility; Quill derives the y-axis domain from the data.
    maxValue: number
    showLegend?: boolean
    yAxisLabel?: string | undefined
}

export function LineChart({ series, labels, showLegend = true, yAxisLabel }: LineChartProps): ReactElement {
    const theme = useMemo(() => buildMcpChartTheme(), [])

    const quillSeries = useMemo<QuillSeries[]>(
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
            <TimeSeriesLineChart series={quillSeries} labels={labels} theme={theme} config={config} />
        </ChartFrame>
    )
}
