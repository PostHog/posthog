import { type ReactElement, useState } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'

import type { TrendsChartDisplayOptions } from 'products/product_analytics/frontend/insights/trends/shared/trendsChartDisplayOptions'
import { TrendsLineChartView } from 'products/product_analytics/frontend/insights/trends/TrendsLineChart/TrendsLineChartView'

import { BarChart, BigNumber, Select, type Series } from './charts'
import { CHART_COLORS, CHART_THEME } from './charts/theme'
import type { TrendsResultItem, TrendsVisualizerProps } from './types'
import { formatDate, getDisplayType, getSeriesLabel, isBarChart } from './utils'

type ChartMode = 'line' | 'bar'

const CHART_MODE_OPTIONS = [
    { value: 'line' as const, label: 'Line' },
    { value: 'bar' as const, label: 'Bar' },
]

// Bar mode still uses the SVG BarChart, which scales against an explicit maxValue.
function prepareChartData(results: TrendsResultItem[]): {
    series: Series[]
    labels: string[]
    maxValue: number
} {
    if (!results || results.length === 0) {
        return { series: [], labels: [], maxValue: 0 }
    }

    const labels = results[0]?.days || results[0]?.labels || []
    let maxValue = 0

    const series = results.map((item, seriesIndex) => {
        const data = item.data || []
        const points = data.map((value, i) => {
            maxValue = Math.max(maxValue, value)
            return {
                x: i,
                y: value,
                label: labels[i] || `${i}`,
            }
        })
        return {
            label: getSeriesLabel(item, seriesIndex),
            points,
        }
    })

    return { series, labels, maxValue: maxValue || 1 }
}

function calculateTotal(results: TrendsResultItem[]): number {
    return results.reduce((sum, item) => {
        if (typeof item.aggregated_value === 'number') {
            return sum + item.aggregated_value
        }
        if (typeof item.count === 'number') {
            return sum + item.count
        }
        if (item.data && item.data.length > 0) {
            return sum + item.data.reduce((a, b) => a + b, 0)
        }
        return sum
    }, 0)
}

export function TrendsVisualizer({ query, results }: TrendsVisualizerProps): ReactElement {
    const displayType = getDisplayType(query)
    const [chartMode, setChartMode] = useState<ChartMode>(isBarChart(displayType) ? 'bar' : 'line')
    const { series, labels, maxValue } = prepareChartData(results)

    if (!results || results.length === 0 || series.length === 0) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyMedia>{emptyStateIllustration('chart')}</EmptyMedia>
                    <EmptyDescription>No data available</EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    if (displayType === 'BoldNumber') {
        const total = calculateTotal(results)
        const label = results[0] ? getSeriesLabel(results[0], 0) : 'Total'
        return <BigNumber value={total} label={label} />
    }

    const lineDisplayOptions: TrendsChartDisplayOptions = {
        isArea: displayType === 'ActionsAreaGraph',
        yFormatterFields: query?.trendsFilter,
        yAxisLabel: results.length === 1 && results[0] ? getSeriesLabel(results[0], 0) : undefined,
        showCrosshair: true,
    }

    return (
        <div>
            <div className="mb-2 flex justify-end">
                {/* eslint-disable-next-line react/forbid-elements */}
                <Select value={chartMode} onChange={setChartMode} options={CHART_MODE_OPTIONS} />
            </div>
            {chartMode === 'bar' ? (
                <BarChart
                    series={series}
                    labels={labels}
                    maxValue={maxValue}
                    yAxisLabel={series.length === 1 ? series[0]?.label : undefined}
                />
            ) : (
                // The shared view is layout-agnostic and sizes to its container; the MCP host
                // imposes no height, so give it one (the web app sizes it via the insight container).
                <div style={{ width: '100%', height: '400px' }}>
                    <TrendsLineChartView
                        results={results.map((item, i) => ({
                            id: i,
                            label: getSeriesLabel(item, i),
                            data: item.data ?? [],
                            days: item.days,
                        }))}
                        labels={labels}
                        theme={CHART_THEME}
                        getColor={(_, index) => CHART_COLORS[index % CHART_COLORS.length]!}
                        displayOptions={lineDisplayOptions}
                        xAxisTickFormatter={(value) => formatDate(value)}
                    />
                </div>
            )}
        </div>
    )
}
