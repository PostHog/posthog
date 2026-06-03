import { type ReactElement, useEffect, useState } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'

import { BigNumber, Select } from './charts'
import { type ChartConfig, ChartSettings, loadChartConfig, saveChartConfig } from './ChartSettings'
import { McpTrendsBarChart } from './McpTrendsBarChart'
import { McpTrendsLineChart } from './McpTrendsLineChart'
import type { ChartDisplayType, TrendsResultItem, TrendsVisualizerProps } from './types'
import { getDisplayType, getSeriesLabel, isBarChart } from './utils'

type ChartType = 'line' | 'area' | 'bar' | 'stacked-bar'

const CHART_TYPE_OPTIONS = [
    { value: 'line' as const, label: 'Line' },
    { value: 'area' as const, label: 'Area' },
    { value: 'bar' as const, label: 'Bar' },
    { value: 'stacked-bar' as const, label: 'Stacked bar' },
]

function defaultChartType(displayType: ChartDisplayType): ChartType {
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

    const isBar = chartType === 'bar' || chartType === 'stacked-bar'
    const chartFamily = isBar ? 'bar' : 'line'
    // Area auto-stacks but derived overlays draw at raw per-series values, so they
    // visually disconnect from the stacked totals. Mirror the web's pattern: disable
    // those toggles in Options and force them off when rendering area mode.
    const derivedSeriesDisabled = chartType === 'area'

    return (
        <div>
            <div className="mb-3 flex items-center justify-between gap-2">
                <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Trends</div>
                <div className="flex items-center gap-2">
                    {/* eslint-disable-next-line react/forbid-elements */}
                    <Select value={chartType} onChange={setChartType} options={CHART_TYPE_OPTIONS} />
                    <ChartSettings
                        chartMode={chartFamily}
                        config={chartConfig}
                        onChange={setChartConfig}
                        derivedSeriesDisabled={derivedSeriesDisabled}
                    />
                </div>
            </div>
            {/* Quill charts render on a flex:1 canvas — they need a sized flex-column parent. */}
            <div className="flex flex-col" style={{ height: 320 }}>
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
                        showTrendLine={chartConfig.showTrendLine && !derivedSeriesDisabled}
                        showMovingAverage={chartConfig.showMovingAverage && !derivedSeriesDisabled}
                        showValueLabels={chartConfig.showValueLabels}
                        showConfidenceIntervals={chartConfig.showConfidenceIntervals && !derivedSeriesDisabled}
                        percentStack={chartConfig.percentStack}
                        yUnit={chartConfig.yUnit}
                    />
                )}
            </div>
        </div>
    )
}
