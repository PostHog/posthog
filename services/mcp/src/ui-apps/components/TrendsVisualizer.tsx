import { type ReactElement, useState } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'
import { BarChart as BarValueChart, SlopeChart, TimeSeriesBarChart, TimeSeriesLineChart } from '@posthog/quill-charts'

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

type ChartMode = 'line' | 'bar' | 'slope'

const CHART_MODE_OPTIONS = [
    { value: 'line' as const, label: 'Line' },
    { value: 'bar' as const, label: 'Bar' },
]

// "Slope" collapses each series to its first and last point — the start-vs-end view a user wants
// when they ask "how much did X change between A and B?" rather than the path between them.
const SLOPE_MODE_OPTION = { value: 'slope' as const, label: 'Slope' }

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
    // Honour the backend slope runner: a SlopeGraph query already comes back as two points per series,
    // so open straight into slope mode rather than line + a manual toggle.
    const [chartMode, setChartMode] = useState<ChartMode>(
        isBarChart(displayType) ? 'bar' : displayType === 'SlopeGraph' ? 'slope' : 'line'
    )

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

    // A slope needs a start and an end, so only offer it when there are at least two time points.
    const slopeAvailable = labels.length >= 2
    const chartModeOptions = slopeAvailable ? [...CHART_MODE_OPTIONS, SLOPE_MODE_OPTION] : CHART_MODE_OPTIONS
    // Results can shrink below two points after slope was selected; fall back rather than render blank.
    const effectiveMode = chartMode === 'slope' && !slopeAvailable ? 'line' : chartMode

    // Build only the active mode's chart model — toggling shouldn't recompute the hidden one.
    const renderChart = (): ReactElement => {
        if (effectiveMode === 'slope') {
            const slopeSeries = trendResults
                .map((item, index) => {
                    if (item.data.length < 2) {
                        return null
                    }
                    return {
                        key: String(item.id),
                        label: item.label,
                        color: colorAt(index),
                        data: [item.data[0]!, item.data[item.data.length - 1]!],
                    }
                })
                .filter((s): s is NonNullable<typeof s> => s !== null)
            const slopeLabels = [formatDate(labels[0]!), formatDate(labels[labels.length - 1]!)]
            return (
                <SlopeChart
                    series={slopeSeries}
                    labels={slopeLabels}
                    theme={CHART_THEME}
                    config={{ showSeriesLabels: false, legend: { show: true, position: 'bottom' } }}
                />
            )
        }
        if (effectiveMode === 'bar') {
            const { series, config } = buildTrendsBarChartModel(trendResults, {
                getColor: (_, index) => colorAt(index),
                labels,
                yAxisLabel,
                isPercentStackView: false,
                isGrouped: false,
                xAxisTickFormatter: (value) => formatDate(value),
                tooltip: TOOLTIP_CONFIG,
            })
            return <TimeSeriesBarChart series={series} labels={labels} theme={CHART_THEME} config={config} />
        }
        const series = buildTrendsSeries(trendResults, {
            isArea: displayType === 'ActionsAreaGraph',
            getColor: (_, index) => colorAt(index),
        })
        const config = buildTrendsLineTimeSeriesConfig({
            results: trendResults,
            trendsFilter: query?.trendsFilter,
            yAxisLabel,
            isPercentStackView: false,
            showCrosshair: true,
            xAxisTickFormatter: (value) => formatDate(value),
        })
        return <TimeSeriesLineChart series={series} labels={labels} theme={CHART_THEME} config={config} />
    }

    return (
        <div>
            <div className="mb-2 flex justify-end">
                {/* eslint-disable-next-line react/forbid-elements */}
                <Select value={effectiveMode} onChange={setChartMode} options={chartModeOptions} />
            </div>
            <div className="flex flex-col w-full h-[400px]">{renderChart()}</div>
        </div>
    )
}
