import { type ReactElement, useState } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'
import { BarChart as BarValueChart, TimeSeriesBarChart, TimeSeriesLineChart } from '@posthog/quill-charts'

import { buildTrendsBarChartModel } from 'products/product_analytics/frontend/insights/trends/TrendsBarChart/trendsBarChartTransforms'
import {
    buildTrendsBarValueConfig,
    buildTrendsBarValueSeries,
} from 'products/product_analytics/frontend/insights/trends/TrendsBarValueChart/trendsBarValueChartTransforms'
import {
    buildTrendsLineTimeSeriesConfig,
    buildTrendsSeries,
} from 'products/product_analytics/frontend/insights/trends/TrendsLineChart/trendsChartTransforms'

import { BigNumber, Select } from './charts'
import { CHART_THEME, colorAt } from './charts/theme'
import type { TrendsResultItem, TrendsVisualizerProps } from './types'
import { formatDate, getDisplayType, getSeriesLabel, isBarChart } from './utils'

type ChartMode = 'line' | 'bar'

const CHART_MODE_OPTIONS = [
    { value: 'line' as const, label: 'Line' },
    { value: 'bar' as const, label: 'Bar' },
]

const TOOLTIP_CONFIG = { pinnable: true, placement: 'top' as const }

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

    const labels = results[0]?.days ?? results[0]?.labels ?? []
    const trendResults = results.map((item, i) => ({
        id: i,
        label: getSeriesLabel(item, i),
        data: item.data ?? [],
        days: item.days,
    }))
    const yAxisLabel = results.length === 1 && results[0] ? getSeriesLabel(results[0], 0) : undefined

    const lineSeries = buildTrendsSeries(trendResults, {
        isArea: displayType === 'ActionsAreaGraph',
        getColor: (_, index) => colorAt(index),
    })

    const lineConfig = buildTrendsLineTimeSeriesConfig({
        results: trendResults,
        trendsFilter: query?.trendsFilter,
        yAxisLabel,
        isPercentStackView: false,
        showCrosshair: true,
        xAxisTickFormatter: (value) => formatDate(value),
    })

    const { series: barSeries, config: barConfig } = buildTrendsBarChartModel(trendResults, {
        getColor: (_, index) => colorAt(index),
        labels,
        yAxisLabel,
        isPercentStackView: false,
        isGrouped: false,
        xAxisTickFormatter: (value) => formatDate(value),
        tooltip: TOOLTIP_CONFIG,
    })

    return (
        <div>
            <div className="mb-2 flex justify-end">
                {/* eslint-disable-next-line react/forbid-elements */}
                <Select value={chartMode} onChange={setChartMode} options={CHART_MODE_OPTIONS} />
            </div>
            <div className="flex flex-col w-full h-[400px]">
                {chartMode === 'bar' ? (
                    <TimeSeriesBarChart series={barSeries} labels={labels} theme={CHART_THEME} config={barConfig} />
                ) : (
                    <TimeSeriesLineChart series={lineSeries} labels={labels} theme={CHART_THEME} config={lineConfig} />
                )}
            </div>
        </div>
    )
}
