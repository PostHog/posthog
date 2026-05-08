import { type ReactElement, useEffect, useState } from 'react'

import { EmptyState } from '@posthog/mosaic'

import { BigNumber, Select } from './charts'
import { type ChartConfig, ChartSettings, loadChartConfig, saveChartConfig } from './ChartSettings'
import { McpTrendsBarChart } from './McpTrendsBarChart'
import { McpTrendsLineChart } from './McpTrendsLineChart'
import type { TrendsResultItem, TrendsVisualizerProps } from './types'
import { getDisplayType, getSeriesLabel, isBarChart } from './utils'

type ChartType = 'line' | 'area' | 'bar' | 'stacked-bar'

const CHART_TYPE_OPTIONS = [
    { value: 'line' as const, label: 'Line' },
    { value: 'area' as const, label: 'Area' },
    { value: 'bar' as const, label: 'Bar' },
    { value: 'stacked-bar' as const, label: 'Stacked bar' },
]

function defaultChartType(displayType: ReturnType<typeof getDisplayType>): ChartType {
    if (displayType === 'ActionsAreaGraph') {
        return 'area'
    }
    if (isBarChart(displayType)) {
        return 'bar'
    }
    return 'line'
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

export function TrendsVisualizer({ query, results, timezone }: TrendsVisualizerProps): ReactElement {
    const displayType = getDisplayType(query)
    const [chartType, setChartType] = useState<ChartType>(defaultChartType(displayType))
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

    const isBar = chartType === 'bar' || chartType === 'stacked-bar'
    const chartFamily = isBar ? 'bar' : 'line'

    return (
        <div>
            <div
                style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: '0.5rem',
                    marginBottom: '0.75rem',
                }}
            >
                <div
                    style={{
                        fontSize: '0.875rem',
                        fontWeight: 600,
                        color: 'var(--color-text-secondary, #6b7280)',
                        textTransform: 'uppercase',
                        letterSpacing: '0.05em',
                    }}
                >
                    Trends
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    {/* eslint-disable-next-line react/forbid-elements */}
                    <Select value={chartType} onChange={setChartType} options={CHART_TYPE_OPTIONS} />
                    <ChartSettings chartMode={chartFamily} config={chartConfig} onChange={setChartConfig} />
                </div>
            </div>
            {/* hog-charts canvas uses flex:1 + minHeight:0 — needs a sized flex column parent. */}
            <div style={{ display: 'flex', flexDirection: 'column', height: 320 }}>
                {isBar ? (
                    <McpTrendsBarChart
                        results={results}
                        interval={query?.interval}
                        timezone={timezone}
                        barLayout={chartType === 'stacked-bar' ? 'stacked' : 'grouped'}
                        showValueLabels={chartConfig.showValueLabels}
                        yUnit={chartConfig.yUnit}
                    />
                ) : (
                    <McpTrendsLineChart
                        results={results}
                        interval={query?.interval}
                        timezone={timezone}
                        fillArea={chartType === 'area'}
                        showTrendLine={chartConfig.showTrendLine}
                        showMovingAverage={chartConfig.showMovingAverage}
                        showValueLabels={chartConfig.showValueLabels}
                        showConfidenceIntervals={chartConfig.showConfidenceIntervals}
                        percentStack={chartConfig.percentStack}
                        yUnit={chartConfig.yUnit}
                    />
                )}
            </div>
        </div>
    )
}
