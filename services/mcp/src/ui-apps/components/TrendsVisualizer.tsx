import { type ReactElement, useState } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'
import {
    BarChart as BarValueChart,
    ciRanges,
    DefaultTooltip,
    SlopeChart,
    TimeSeriesBarChart,
    TimeSeriesLineChart,
    type TooltipContext,
} from '@posthog/quill-charts'

import { buildTrendsBarChartModel } from 'products/product_analytics/frontend/insights/trends/TrendsBarChart/trendsBarChartTransforms'
import {
    buildTrendsBarValueConfig,
    buildTrendsBarValueSeries,
} from 'products/product_analytics/frontend/insights/trends/TrendsBarValueChart/trendsBarValueChartTransforms'
import {
    buildTrendsLineTimeSeriesConfig,
    buildTrendsSeries,
} from 'products/product_analytics/frontend/insights/trends/TrendsLineChart/trendsChartTransforms'

import { ChartHeader } from './ChartHeader'
import { BigNumber, Select } from './charts'
import { colorAt, useMcpChartTheme } from './charts/theme'
import { ChartSettings } from './ChartSettings'
import {
    type ChartType,
    chartConfigFromTrendsFilter,
    defaultChartType,
    isBarFamily,
    resolveChartView,
    supportsPercentStack,
} from './chartSettingsConfig'
import type { TrendsResultItem, TrendsVisualizerProps } from './types'
import { formatDate, formatTooltipDate, getDisplayType, getSeriesLabel } from './utils'

const TITLE = 'Trends'

const CHART_TYPE_OPTIONS = [
    { value: 'line' as const, label: 'Line' },
    { value: 'area' as const, label: 'Area' },
    { value: 'bar' as const, label: 'Bar' },
    { value: 'stacked-bar' as const, label: 'Stacked bar' },
]

const SLOPE_TYPE_OPTION = { value: 'slope' as const, label: 'Slope' }

const TOOLTIP_CONFIG = { pinnable: true, placement: 'cursor' as const }

// DefaultTooltip shows the raw x label; format it like the axis.
const renderDateTooltip = (ctx: TooltipContext): ReactElement => (
    <DefaultTooltip {...ctx} label={formatTooltipDate(ctx.label)} />
)

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
    const [chartType, setChartType] = useState<ChartType>(defaultChartType(displayType))
    const [chartConfig, setChartConfig] = useState(() => chartConfigFromTrendsFilter(query?.trendsFilter))
    const theme = useMcpChartTheme()

    if (!results || results.length === 0) {
        return (
            <div>
                <ChartHeader title={TITLE} />
                <Empty>
                    <EmptyHeader>
                        <EmptyMedia>{emptyStateIllustration('chart')}</EmptyMedia>
                        <EmptyDescription>No data available</EmptyDescription>
                    </EmptyHeader>
                </Empty>
            </div>
        )
    }

    if (displayType === 'BoldNumber') {
        const total = calculateTotal(results)
        const label = results[0] ? getSeriesLabel(results[0], 0) : 'Total'
        return (
            <div>
                <ChartHeader title={TITLE} />
                <BigNumber value={total} label={label} />
            </div>
        )
    }

    // ActionsBarValue is aggregated totals per series (no days[]) — a horizontal bar, not a time series.
    if (displayType === 'ActionsBarValue') {
        const items = results.map((item, i) => ({
            label: getSeriesLabel(item, i),
            value: item.aggregated_value,
        }))
        const barSeries = buildTrendsBarValueSeries(items, { getColor: colorAt })
        const barConfig = buildTrendsBarValueConfig()
        return (
            <div>
                <ChartHeader title={TITLE} />
                <div className="flex flex-col w-full h-[400px]">
                    <BarValueChart
                        series={barSeries}
                        labels={items.map((item) => item.label)}
                        theme={theme}
                        config={barConfig}
                    />
                </div>
            </div>
        )
    }

    const labels = results[0]?.days ?? results[0]?.labels ?? []
    const trendResults = results.map((item, i) => ({
        id: i,
        label: getSeriesLabel(item, i),
        data: item.data ?? [],
        days: item.days,
        incompleteEnd: !!item.incomplete_end,
    }))
    const { slopeAvailable, effectiveType } = resolveChartView(chartType, labels.length)
    const chartTypeOptions = slopeAvailable ? [...CHART_TYPE_OPTIONS, SLOPE_TYPE_OPTION] : CHART_TYPE_OPTIONS

    // Area auto-stacks, so derived overlays would draw against the stacked totals — disable them.
    const derivedSeriesDisabled = effectiveType === 'area'
    const isPercentStackView = chartConfig.percentStack && supportsPercentStack(effectiveType)
    const effectiveTrendsFilter = { ...query?.trendsFilter, aggregationAxisFormat: chartConfig.yUnit }
    const valueLabels = chartConfig.showValueLabels ? true : undefined

    const renderChart = (): ReactElement => {
        if (effectiveType === 'slope') {
            const slopeSeries = trendResults
                .filter((item) => item.data.length >= 2)
                .map((item) => ({
                    key: String(item.id),
                    label: item.label,
                    color: colorAt(item.id),
                    data: item.data,
                    meta: item.incompleteEnd ? { incompleteEnd: true } : undefined,
                }))
            const slopeLabels = labels.map((label) => formatDate(String(label)))
            return (
                <SlopeChart
                    series={slopeSeries}
                    labels={slopeLabels}
                    theme={theme}
                    config={{ showSeriesLabels: false, legend: { show: true, position: 'bottom' } }}
                />
            )
        }
        if (isBarFamily(effectiveType)) {
            const { series, config } = buildTrendsBarChartModel(trendResults, {
                getColor: (_, index) => colorAt(index),
                labels,
                trendsFilter: effectiveTrendsFilter,
                isPercentStackView,
                isGrouped: effectiveType === 'bar',
                valueLabels,
                xAxisTickFormatter: (value) => formatDate(value),
                tooltip: TOOLTIP_CONFIG,
            })
            return (
                <TimeSeriesBarChart
                    series={series}
                    labels={labels}
                    theme={theme}
                    config={config}
                    tooltip={renderDateTooltip}
                />
            )
        }
        const series = buildTrendsSeries(trendResults, {
            isArea: effectiveType === 'area',
            getColor: (_, index) => colorAt(index),
        })
        const config = buildTrendsLineTimeSeriesConfig({
            results: trendResults,
            trendsFilter: effectiveTrendsFilter,
            isPercentStackView,
            showTrendLines: chartConfig.showTrendLine && !derivedSeriesDisabled,
            showConfidenceIntervals: chartConfig.showConfidenceIntervals && !derivedSeriesDisabled,
            confidenceLevel: chartConfig.confidenceLevel,
            ciRanges,
            valueLabels,
            showCrosshair: true,
            xAxisTickFormatter: (value) => formatDate(value),
            tooltip: TOOLTIP_CONFIG,
        })
        return (
            <TimeSeriesLineChart
                series={series}
                labels={labels}
                theme={theme}
                config={config}
                tooltip={renderDateTooltip}
            />
        )
    }

    return (
        <div>
            <ChartHeader title={TITLE}>
                {/* eslint-disable-next-line react/forbid-elements */}
                <Select value={effectiveType} onChange={setChartType} options={chartTypeOptions} />
                {effectiveType !== 'slope' && (
                    <ChartSettings
                        family={isBarFamily(effectiveType) ? 'bar' : 'line'}
                        config={chartConfig}
                        onChange={setChartConfig}
                        derivedSeriesDisabled={derivedSeriesDisabled}
                        percentStackDisabled={!supportsPercentStack(effectiveType)}
                    />
                )}
            </ChartHeader>
            <div className="flex flex-col w-full h-[400px]">{renderChart()}</div>
        </div>
    )
}
