import type { ReactElement } from 'react'

import { buildYTickFormatter, type ChartTheme, TimeSeriesBarChart, TimeSeriesLineChart } from '@posthog/quill-charts'

import type { StoryEvidenceChartData } from './explainChartTypes'

const Y_TICK_FORMATTER = buildYTickFormatter({ format: 'short' })

export interface StoryEvidenceChartProps {
    chart: StoryEvidenceChartData
    theme: ChartTheme
    className: string
}

export function StoryEvidenceChart({ chart, theme, className }: StoryEvidenceChartProps): ReactElement {
    const series = chart.series.map((item, index) => ({
        key: String(index),
        label: item.name,
        data: item.values.map((value) => value ?? NaN),
    }))
    // quill-charts positions points by label, so a repeated label would send the line backwards.
    const keys = chart.labels.map((_, index) => String(index))
    // Results saved before `ticks` existed carry only `labels`.
    const xAxis = { tickFormatter: (key: string): string => (chart.ticks ?? chart.labels)[Number(key)] ?? key }
    const yAxis = { tickFormatter: Y_TICK_FORMATTER, showGrid: true, label: chart.yAxisLabel ?? undefined }
    const tooltip = { labelFormatter: (key: string): string => chart.labels[Number(key)] ?? key }
    const legend = { show: series.length > 1 }
    return (
        <div className={`flex w-full flex-col ${className}`} data-attr="explain-chart-evidence-inline-chart">
            {chart.type === 'bar' ? (
                <TimeSeriesBarChart
                    series={series}
                    labels={keys}
                    theme={theme}
                    config={{ xAxis, yAxis, tooltip, legend, barLayout: 'grouped' }}
                />
            ) : (
                <TimeSeriesLineChart
                    series={series}
                    labels={keys}
                    theme={theme}
                    config={{ xAxis, yAxis, tooltip, legend, showCrosshair: true }}
                />
            )}
        </div>
    )
}
