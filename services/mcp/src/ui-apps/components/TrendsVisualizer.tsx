import { type ReactElement, useState } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'
import { BarChart as BarValueChart, TimeSeriesLineChart } from '@posthog/quill-charts'

import {
    buildTrendsBarValueConfig,
    buildTrendsBarValueSeries,
} from 'products/product_analytics/frontend/insights/trends/TrendsBarValueChart/trendsBarValueChartTransforms'
import {
    buildTrendsLineTimeSeriesConfig,
    buildTrendsSeries,
} from 'products/product_analytics/frontend/insights/trends/TrendsLineChart/trendsChartTransforms'

import { BarChart, BigNumber, Select, type Series } from './charts'
import { CHART_THEME, colorAt } from './charts/theme'
import type { TrendsResultItem, TrendsVisualizerProps } from './types'
import { formatDate, getDisplayType, getSeriesLabel, isBarChart } from './utils'

type ChartMode = 'line' | 'bar'

const CHART_MODE_OPTIONS = [
    { value: 'line' as const, label: 'Line' },
    { value: 'bar' as const, label: 'Bar' },
]

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

    // ActionsBarValue returns aggregated_value per series (empty data[]/days[]) — render a
    // horizontal bar of totals, not a time series, so there's no line/bar mode toggle.
    if (displayType === 'ActionsBarValue') {
        const items = results.map((item, i) => ({
            label: getSeriesLabel(item, i),
            value: item.aggregated_value,
        }))
        const barSeries = buildTrendsBarValueSeries(items, { getColor: colorAt })
        const barConfig = buildTrendsBarValueConfig()
        return (
            <div className="flex flex-col w-full h-[400px]">
                <BarValueChart
                    series={barSeries}
                    labels={items.map((item) => item.label)}
                    theme={CHART_THEME}
                    config={barConfig}
                />
            </div>
        )
    }

    const lineResults = results.map((item, i) => ({
        id: i,
        label: getSeriesLabel(item, i),
        data: item.data ?? [],
        days: item.days,
    }))

    const lineSeries = buildTrendsSeries(lineResults, {
        isArea: displayType === 'ActionsAreaGraph',
        getColor: (_, index) => colorAt(index),
    })

    const lineConfig = buildTrendsLineTimeSeriesConfig({
        results: lineResults,
        trendsFilter: query?.trendsFilter,
        yAxisLabel: results.length === 1 && results[0] ? getSeriesLabel(results[0], 0) : undefined,
        isPercentStackView: false,
        showCrosshair: true,
        xAxisTickFormatter: (value) => formatDate(value),
    })

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
                <div className="flex flex-col w-full h-[400px]">
                    <TimeSeriesLineChart series={lineSeries} labels={labels} theme={CHART_THEME} config={lineConfig} />
                </div>
            )}
        </div>
    )
}
