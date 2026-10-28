import type { ReactElement } from 'react'

import { buildYTickFormatter, type ChartTheme, TimeSeriesBarChart, TimeSeriesLineChart } from '@posthog/quill-charts'

import type { StoryEvidenceChartData } from './explainChartTypes'

const Y_AXIS = { tickFormatter: buildYTickFormatter({ format: 'short' }), showGrid: true }

export interface StoryEvidenceChartProps {
    chart: StoryEvidenceChartData
    theme: ChartTheme
    className: string
}

export function StoryEvidenceChart({ chart, theme, className }: StoryEvidenceChartProps): ReactElement {
    const series = chart.series.map((item, index) => ({ key: String(index), label: item.name, data: item.values }))
    const legend = { show: series.length > 1 }
    return (
        <div className={`flex w-full flex-col ${className}`} data-attr="explain-chart-evidence-inline-chart">
            {chart.type === 'bar' ? (
                <TimeSeriesBarChart
                    series={series}
                    labels={chart.labels}
                    theme={theme}
                    config={{ yAxis: Y_AXIS, legend, barLayout: 'grouped' }}
                />
            ) : (
                <TimeSeriesLineChart
                    series={series}
                    labels={chart.labels}
                    theme={theme}
                    config={{ yAxis: Y_AXIS, legend, showCrosshair: true }}
                />
            )}
        </div>
    )
}
