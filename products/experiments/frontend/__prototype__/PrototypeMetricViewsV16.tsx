/** Scratch prototype v16: result views as two choices, one chart per metric or one for all, and the chart type. Not committed. */
import { useMemo } from 'react'

import { IconGridMasonry, IconLineGraph, IconRetentionHeatmap, IconStickiness, IconTrends } from '@posthog/icons'
import { Card, Text, ToggleGroup, ToggleGroupItem } from '@posthog/quill'
import { BoxPlot, type BoxPlotDatum, type BoxPlotSeries, Heatmap, type HeatmapCellDatum } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import type { PrototypeMetric, PrototypeVariantResult } from './prototypeData'
import {
    AllMetricsTrendChart,
    CandlestickChart,
    formatDelta,
    formatPercent,
    HALF_INTERVAL_RATIO,
    isSignificant,
    isWin,
    MetricMatrix,
    useResolvedTokens,
} from './PrototypeMetricViews'

export const RESULT_LAYOUT = { perMetric: 'per-metric', allMetrics: 'all-metrics' } as const
export type ResultLayout = (typeof RESULT_LAYOUT)[keyof typeof RESULT_LAYOUT]

export const RESULT_CHART = { trend: 'trend', candlestick: 'candlestick', matrix: 'matrix' } as const
export type ResultChart = (typeof RESULT_CHART)[keyof typeof RESULT_CHART]

const LAYOUT_OPTIONS: { value: ResultLayout; label: string; icon: JSX.Element }[] = [
    { value: 'per-metric', label: 'Chart per metric', icon: <IconGridMasonry /> },
    { value: 'all-metrics', label: 'One chart', icon: <IconLineGraph /> },
]

const CHART_OPTIONS: { value: ResultChart; label: string; icon: JSX.Element }[] = [
    { value: 'trend', label: 'Delta over time', icon: <IconTrends /> },
    { value: 'candlestick', label: 'Candlestick', icon: <IconStickiness /> },
    { value: 'matrix', label: 'Matrix', icon: <IconRetentionHeatmap /> },
]

const HINTS: Record<ResultLayout, Record<ResultChart, string>> = {
    'per-metric': {
        trend: 'Delta over time with its 95% interval, next to each metric',
        candlestick: 'Latest delta with its 50% and 95% intervals, next to each metric',
        matrix: 'Delta and chance to win, colored by significant change, next to each metric',
    },
    'all-metrics': {
        trend: 'Every metric on one delta over time chart',
        candlestick: 'Every metric on one axis, so sizes compare across metrics',
        matrix: 'Metrics by variant, colored by significant change',
    },
}

/** Two choices the user can combine: where the charts go, and which chart it is. */
export function ResultViewSwitch({
    layout,
    chart,
    onLayoutChange,
    onChartChange,
}: {
    layout: ResultLayout
    chart: ResultChart
    onLayoutChange: (layout: ResultLayout) => void
    onChartChange: (chart: ResultChart) => void
}): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-2" data-attr="result-view-switch">
            <Text size="xs" variant="muted">
                Show results as
            </Text>
            <ToggleGroup
                variant="outline"
                size="sm"
                value={[layout]}
                onValueChange={(value: string[]) => value[0] && onLayoutChange(value[0] as ResultLayout)}
                aria-label="Chart layout"
                data-attr="result-layout"
            >
                {LAYOUT_OPTIONS.map((option) => (
                    <ToggleGroupItem key={option.value} value={option.value}>
                        {option.icon}
                        {option.label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
            <ToggleGroup
                variant="outline"
                size="sm"
                value={[chart]}
                onValueChange={(value: string[]) => value[0] && onChartChange(value[0] as ResultChart)}
                aria-label="Chart type"
                data-attr="result-chart"
            >
                {CHART_OPTIONS.map((option) => (
                    <ToggleGroupItem key={option.value} value={option.value}>
                        {option.icon}
                        {option.label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
            <Text size="xs" variant="muted">
                {HINTS[layout][chart]}
            </Text>
        </div>
    )
}

function candle(variant: PrototypeVariantResult): BoxPlotDatum {
    if (variant.delta === null || variant.interval === null) {
        /** Control is the baseline, drawn as a point at 0% so the chart always shows where zero is. */
        return { min: 0, p25: 0, median: 0, mean: 0, p75: 0, max: 0 }
    }
    const half = ((variant.interval[1] - variant.interval[0]) / 2) * HALF_INTERVAL_RATIO
    return {
        min: variant.interval[0],
        p25: variant.delta - half,
        median: variant.delta,
        mean: variant.delta,
        p75: variant.delta + half,
        max: variant.interval[1],
    }
}

/** Every metric on one value axis, one box per variant, so a +4% on one metric looks as big as a +4% on another. */
export function AllMetricsCandlestick({
    metrics,
    colors,
}: {
    metrics: PrototypeMetric[]
    colors: Record<string, string>
}): JSX.Element {
    const theme = useChartTheme()
    const series: BoxPlotSeries[] = useMemo(
        () =>
            metrics[0].variants.map(({ key }) => ({
                key,
                label: key,
                color: colors[key],
                data: metrics.map((metric) => {
                    const variant = metric.variants.find((item) => item.key === key)
                    return variant ? candle(variant) : null
                }),
            })),
        [metrics, colors]
    )
    return (
        <div className="flex flex-col" style={{ height: metrics.length * 72 + 64 }}>
            <BoxPlot
                series={series}
                labels={metrics.map((metric, index) => `${index + 1}. ${metric.name}`)}
                theme={theme}
                config={{
                    axisOrientation: 'horizontal',
                    showGrid: true,
                    yTickFormatter: formatPercent,
                    legend: { show: true, position: 'bottom', align: 'start' },
                    margins: { left: 150, right: 16 },
                }}
            />
        </div>
    )
}

const ROW_MATRIX_COLUMNS = ['Delta', 'Chance to win']

/** One metric's variants as colored cells that line up with the table rows: delta and chance to win. */
export function MetricRowMatrix({ metric, height }: { metric: PrototypeMetric; height: number }): JSX.Element {
    const theme = useChartTheme()
    const [ref, tokens] = useResolvedTokens()
    /** The heatmap draws its first row at the bottom, so reverse the variants to match the table. */
    const rows = [...metric.variants].reverse()
    const cells = rows.map((variant) =>
        variant.delta === null
            ? [0, 0]
            : [Math.abs(variant.delta) * 100, Math.abs((variant.chanceToWin ?? 0.5) - 0.5) * 20]
    )
    const tone = (variant: PrototypeVariantResult): string | null => {
        if (!tokens || variant.delta === null) {
            return null
        }
        if (!isSignificant(variant)) {
            return tokens['muted-foreground']
        }
        return isWin(variant, metric.goal) ? tokens['success-foreground'] : tokens['destructive-foreground']
    }
    return (
        <div ref={ref} className="flex flex-col" style={{ height }}>
            {tokens && (
                <Heatmap
                    xLabels={ROW_MATRIX_COLUMNS}
                    yLabels={rows.map((variant) => variant.key)}
                    cells={cells}
                    theme={theme}
                    config={{
                        colorScale: 'linear',
                        hideYAxis: true,
                        hideXAxis: true,
                        cellLabel: (cell: HeatmapCellDatum) => {
                            const variant = rows[cell.yIndex]
                            if (variant.delta === null) {
                                return cell.xIndex === 0 ? 'Baseline' : null
                            }
                            return cell.xIndex === 0
                                ? formatDelta(variant.delta)
                                : `${Math.round((variant.chanceToWin ?? 0) * 100)}% to win`
                        },
                        cellStyle: (cell: HeatmapCellDatum) => {
                            const color = tone(rows[cell.yIndex])
                            return color ? { color, filled: true } : null
                        },
                        margins: { left: 4, right: 4, top: 6, bottom: 6 },
                    }}
                />
            )}
        </div>
    )
}

/** The chart drawn in a metric's rows, for the "Chart per metric" layout. */
export function MetricRowChart({
    chart,
    metric,
    height,
    trend,
}: {
    chart: ResultChart
    metric: PrototypeMetric
    height: number
    trend: JSX.Element
}): JSX.Element {
    if (chart === RESULT_CHART.candlestick) {
        return <CandlestickChart metric={metric} height={height} />
    }
    if (chart === RESULT_CHART.matrix) {
        return <MetricRowMatrix metric={metric} height={height} />
    }
    return trend
}

/** The single chart above a section's table, for the "One chart" layout. */
export function SectionResultChart({
    chart,
    title,
    metrics,
    colors,
    limit,
}: {
    chart: ResultChart
    title: string
    metrics: PrototypeMetric[]
    colors: Record<string, string>
    limit: number
}): JSX.Element {
    const kind = title.toLowerCase().replace(' metrics', '')
    const caption = {
        trend: `Delta over time for every ${kind} metric. Hover the chart for each value.`,
        candlestick: `Latest delta for every ${kind} metric on one axis. Box is the 50% interval, whiskers the 95% interval.`,
        matrix: 'Each cell shows the delta and the chance to win. Color shows a significant change; gray is not significant.',
    }[chart]
    return (
        <Card size="sm" className="mb-3 gap-2" data-attr={`metric-section-chart-${chart}`}>
            <Text size="xs" variant="muted">
                {caption}
            </Text>
            {chart === RESULT_CHART.trend && <AllMetricsTrendChart metrics={metrics} limit={limit} />}
            {chart === RESULT_CHART.candlestick && <AllMetricsCandlestick metrics={metrics} colors={colors} />}
            {chart === RESULT_CHART.matrix && <MetricMatrix metrics={metrics} />}
        </Card>
    )
}
