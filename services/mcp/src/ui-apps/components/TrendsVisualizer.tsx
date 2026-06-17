import { type ReactElement, useState } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'
import {
    BarChart as BarValueChart,
    ciRanges,
    SlopeChart,
    TimeSeriesBarChart,
    TimeSeriesLineChart,
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

import { BigNumber, Select } from './charts'
import { CHART_THEME, colorAt } from './charts/theme'
import { ChartSettings } from './ChartSettings'
import {
    type ChartType,
    chartConfigFromTrendsFilter,
    defaultChartType,
    isBarFamily,
    supportsPercentStack,
} from './chartSettingsConfig'
import type { TrendsResultItem, TrendsVisualizerProps } from './types'
import { formatDate, getDisplayType, getSeriesLabel } from './utils'

const CHART_TYPE_OPTIONS = [
    { value: 'line' as const, label: 'Line' },
    { value: 'area' as const, label: 'Area' },
    { value: 'bar' as const, label: 'Bar' },
    { value: 'stacked-bar' as const, label: 'Stacked bar' },
]

// "Slope" collapses each series to its first and last point — the start-vs-end view a user wants
// when they ask "how much did X change between A and B?" rather than the path between them.
const SLOPE_TYPE_OPTION = { value: 'slope' as const, label: 'Slope' }

const TOOLTIP_CONFIG = { pinnable: true, placement: 'cursor' as const }

const TITLE_CLASS = 'text-xs font-semibold uppercase tracking-wider text-muted-foreground'

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

export function TrendsVisualizer({ query, results, title }: TrendsVisualizerProps): ReactElement {
    const displayType = getDisplayType(query)
    // Honour the backend slope runner: a SlopeGraph query already comes back as two points per series,
    // so defaultChartType opens straight into slope mode rather than line + a manual toggle.
    const [chartType, setChartType] = useState<ChartType>(defaultChartType(displayType))
    const [chartConfig, setChartConfig] = useState(() => chartConfigFromTrendsFilter(query?.trendsFilter))

    if (!results || results.length === 0) {
        return (
            <div>
                {title && <div className={`mb-4 ${TITLE_CLASS}`}>{title}</div>}
                <Empty>
                    <EmptyHeader>
                        <EmptyMedia>{emptyStateIllustration('chart')}</EmptyMedia>
                        <EmptyDescription>No data available</EmptyDescription>
                    </EmptyHeader>
                </Empty>
            </div>
        )
    }

    // BoldNumber and ActionsBarValue aren't time series — no chart-type select, no options.
    if (displayType === 'BoldNumber') {
        const total = calculateTotal(results)
        const label = results[0] ? getSeriesLabel(results[0], 0) : 'Total'
        return (
            <div>
                {title && <div className={`mb-4 ${TITLE_CLASS}`}>{title}</div>}
                <BigNumber value={total} label={label} />
            </div>
        )
    }

    // ActionsBarValue returns aggregated_value per series (empty data[]/days[]) — render a
    // horizontal bar of totals, not a time series.
    if (displayType === 'ActionsBarValue') {
        const items = results.map((item, i) => ({
            label: getSeriesLabel(item, i),
            value: item.aggregated_value,
        }))
        const barSeries = buildTrendsBarValueSeries(items, { getColor: colorAt })
        const barConfig = buildTrendsBarValueConfig()
        return (
            <div>
                {title && <div className={`mb-4 ${TITLE_CLASS}`}>{title}</div>}
                <div className="flex flex-col w-full h-[400px]">
                    <BarValueChart
                        series={barSeries}
                        labels={items.map((item) => item.label)}
                        theme={CHART_THEME}
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
    // A slope needs a start and an end, so only offer it when there are at least two time points.
    const slopeAvailable = labels.length >= 2
    const chartTypeOptions = slopeAvailable ? [...CHART_TYPE_OPTIONS, SLOPE_TYPE_OPTION] : CHART_TYPE_OPTIONS
    // Results can shrink below two points after slope was selected; fall back rather than render blank.
    const effectiveType = chartType === 'slope' && !slopeAvailable ? 'line' : chartType

    // Area auto-stacks but derived overlays draw at raw per-series values, so they visually
    // disconnect from the stacked totals. Mirror the web's pattern: disable those toggles in
    // Options and force them off when rendering area mode.
    const derivedSeriesDisabled = effectiveType === 'area'
    const isPercentStackView = chartConfig.percentStack && supportsPercentStack(effectiveType)
    // The dialog's y-unit choice wins over whatever the saved insight specified.
    const effectiveTrendsFilter = { ...query?.trendsFilter, aggregationAxisFormat: chartConfig.yUnit }
    // `valueLabels: true` falls back to the y-tick formatter, which already respects the
    // y-unit and percent-stack view.
    const valueLabels = chartConfig.showValueLabels ? true : undefined

    // Build only the active mode's chart model — toggling shouldn't recompute the hidden one.
    const renderChart = (): ReactElement => {
        if (effectiveType === 'slope') {
            // Hand quill the full series and labels — it reduces to the first and last point itself,
            // so the slope shaping lives once in quill, not here. The backend's incomplete_end flag is
            // forwarded so the provisional end dashes exactly as it does in the insight.
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
                    theme={CHART_THEME}
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
            return <TimeSeriesBarChart series={series} labels={labels} theme={CHART_THEME} config={config} />
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
        return <TimeSeriesLineChart series={series} labels={labels} theme={CHART_THEME} config={config} />
    }

    return (
        <div>
            <div className="mb-2 flex items-center gap-2">
                {title && <div className={TITLE_CLASS}>{title}</div>}
                <div className="ml-auto flex items-center gap-2">
                    {/* eslint-disable-next-line react/forbid-elements */}
                    <Select value={effectiveType} onChange={setChartType} options={chartTypeOptions} />
                    {/* Slope bypasses the chart-config pipeline entirely — none of these options apply. */}
                    {effectiveType !== 'slope' && (
                        <ChartSettings
                            chartMode={isBarFamily(effectiveType) ? 'bar' : 'line'}
                            config={chartConfig}
                            onChange={setChartConfig}
                            derivedSeriesDisabled={derivedSeriesDisabled}
                            percentStackDisabled={!supportsPercentStack(effectiveType)}
                        />
                    )}
                </div>
            </div>
            <div className="flex flex-col w-full h-[400px]">{renderChart()}</div>
        </div>
    )
}
