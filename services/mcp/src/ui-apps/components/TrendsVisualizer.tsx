import { type ReactElement, useEffect, useState } from 'react'

import { EmptyState } from '@posthog/mosaic'

import { BigNumber, Select } from './charts'
import { type ChartConfig, ChartSettings, loadChartConfig, saveChartConfig } from './ChartSettings'
import { McpTrendsBarChart } from './McpTrendsBarChart'
import { McpTrendsLineChart } from './McpTrendsLineChart'
import type { TrendsResultItem, TrendsVisualizerProps } from './types'
import { getDisplayType, getSeriesLabel, isBarChart } from './utils'

type ChartMode = 'line' | 'bar'

const CHART_MODE_OPTIONS = [
    { value: 'line' as const, label: 'Line' },
    { value: 'bar' as const, label: 'Bar' },
]

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

export function TrendsVisualizer({ query, results, timezone }: TrendsVisualizerProps): ReactElement {
    const displayType = getDisplayType(query)
    const [chartMode, setChartMode] = useState<ChartMode>(isBarChart(displayType) ? 'bar' : 'line')
    const [chartConfig, setChartConfig] = useState<ChartConfig>(loadChartConfig)

    useEffect(() => {
        saveChartConfig(chartConfig)
    }, [chartConfig])

    if (!results || results.length === 0) {
        return <EmptyState icon="chart" description="No data available" />
    }

    if (displayType === 'BoldNumber') {
        const total = calculateTotal(results)
        const label = results[0] ? getSeriesLabel(results[0], 0) : 'Total'
        return <BigNumber value={total} label={label} />
    }

    return (
        <div>
            <div
                style={{
                    display: 'flex',
                    justifyContent: 'flex-end',
                    alignItems: 'center',
                    gap: '0.5rem',
                    marginBottom: '0.5rem',
                }}
            >
                {/* eslint-disable-next-line react/forbid-elements */}
                <Select value={chartMode} onChange={setChartMode} options={CHART_MODE_OPTIONS} />
                <ChartSettings chartMode={chartMode} config={chartConfig} onChange={setChartConfig} />
            </div>
            {chartMode === 'bar' ? (
                <McpTrendsBarChart
                    results={results}
                    interval={query?.interval}
                    timezone={timezone}
                    barLayout={chartConfig.barLayout}
                    showValueLabels={chartConfig.showValueLabels}
                />
            ) : (
                <McpTrendsLineChart
                    results={results}
                    interval={query?.interval}
                    timezone={timezone}
                    showTrendLine={chartConfig.showTrendLine}
                    showMovingAverage={chartConfig.showMovingAverage}
                    showValueLabels={chartConfig.showValueLabels}
                    percentStack={chartConfig.percentStack}
                />
            )}
        </div>
    )
}
