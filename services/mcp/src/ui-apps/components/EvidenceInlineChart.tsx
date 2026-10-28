import type { ReactElement } from 'react'

import { TimeSeriesBarChart, TimeSeriesLineChart } from '@posthog/quill-charts'

import type { StoryEvidenceChart } from 'products/product_analytics/mcp/apps/explainChart/explainChartTypes'

import { colorAt, useMcpChartTheme } from './charts/theme'
import { formatNumber } from './utils'

export interface EvidenceInlineChartProps {
    chart: StoryEvidenceChart
    className: string
}

export function EvidenceInlineChart({ chart, className }: EvidenceInlineChartProps): ReactElement {
    const theme = useMcpChartTheme()
    const series = chart.series.map((item, index) => ({
        key: String(index),
        label: item.name,
        data: item.values,
        color: colorAt(index),
    }))
    const config = {
        yAxis: { tickFormatter: formatNumber, showGrid: true },
        legend: { show: series.length > 1 },
    }
    return (
        <div className={`flex w-full flex-col ${className}`} data-attr="explain-chart-evidence-inline-chart">
            {chart.type === 'bar' ? (
                <TimeSeriesBarChart
                    series={series}
                    labels={chart.labels}
                    theme={theme}
                    config={{ ...config, barLayout: 'grouped' }}
                />
            ) : (
                <TimeSeriesLineChart
                    series={series}
                    labels={chart.labels}
                    theme={theme}
                    config={{ ...config, showCrosshair: true }}
                />
            )}
        </div>
    )
}
