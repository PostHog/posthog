import type { ReactElement } from 'react'

import { Text } from '@posthog/quill'
import { buildYTickFormatter, type ChartTheme, TimeSeriesBarChart, TimeSeriesLineChart } from '@posthog/quill-charts'

import type { StoryEvidenceChartData } from './explainChartTypes'

const Y_TICK_FORMATTER = buildYTickFormatter({ format: 'short' })

export interface StoryEvidenceChartProps {
    chart: StoryEvidenceChartData
    theme: ChartTheme
    className: string
}

export function StoryEvidenceChart({ chart, theme, className }: StoryEvidenceChartProps): ReactElement {
    const series = chart.series.map((item, index) => ({ key: String(index), label: item.name, data: item.values }))
    // quill-charts positions points by label, so a repeated label would send the line backwards.
    const keys = chart.labels.map((_, index) => String(index))
    const labelAt = (key: string): string => chart.labels[Number(key)] ?? key
    const xAxis = { tickFormatter: labelAt }
    const yAxis = { tickFormatter: Y_TICK_FORMATTER, showGrid: true, label: chart.yAxisLabel ?? undefined }
    const tooltip = { labelFormatter: labelAt }
    const legend = { show: series.length > 1 }
    return (
        <div className={`flex w-full flex-col gap-2 ${className}`} data-attr="explain-chart-evidence-inline-chart">
            {chart.title && (
                <Text size="sm" weight="medium">
                    {chart.title}
                </Text>
            )}
            <div className="flex min-h-0 w-full flex-1 flex-col">
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
        </div>
    )
}
