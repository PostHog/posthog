/** Scratch prototype v15: the ways to show metric results, and the switch between them. Not committed. */
import { useEffect, useMemo, useRef, useState } from 'react'

import { IconGridMasonry, IconLineGraph, IconRetentionHeatmap, IconScatter, IconStickiness } from '@posthog/icons'
import { Card, Text, ToggleGroup, ToggleGroupItem } from '@posthog/quill'
import {
    BoxPlot,
    type BoxPlotSeries,
    Heatmap,
    type HeatmapCellDatum,
    LineChart,
    type LineChartConfig,
    ReferenceLine,
    ScatterChart,
    type ScatterSeries,
    type Series,
} from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { dayjs } from 'lib/dayjs'

import {
    EXPOSURES,
    METRIC_GOAL,
    type MetricGoal,
    type PrototypeMetric,
    type PrototypeVariantResult,
} from './prototypeData'
import { metricTrends } from './prototypeTimeseries'

export const METRIC_VIEW = {
    perMetric: 'per-metric',
    oneChart: 'one-chart',
    candlestick: 'candlestick',
    matrix: 'matrix',
    effectMap: 'effect-map',
} as const
export type MetricView = (typeof METRIC_VIEW)[keyof typeof METRIC_VIEW]

const VIEW_OPTIONS: { value: MetricView; label: string; hint: string; icon: JSX.Element }[] = [
    {
        value: 'per-metric',
        label: 'Per metric',
        hint: 'Delta over time next to each metric',
        icon: <IconGridMasonry />,
    },
    {
        value: 'one-chart',
        label: 'One chart',
        hint: 'Every metric on one delta over time chart',
        icon: <IconLineGraph />,
    },
    {
        value: 'candlestick',
        label: 'Candlestick',
        hint: 'Latest delta with its 50% and 95% intervals',
        icon: <IconStickiness />,
    },
    {
        value: 'matrix',
        label: 'Matrix',
        hint: 'Metrics by variant, colored by significant change',
        icon: <IconRetentionHeatmap />,
    },
    {
        value: 'effect-map',
        label: 'Effect map',
        hint: 'Delta against chance to win, one point per metric and variant',
        icon: <IconScatter />,
    },
]

/** Views that draw one chart above the table instead of a chart in each metric's rows. */
export const SECTION_CHART_VIEWS: MetricView[] = ['one-chart', 'matrix', 'effect-map']

export function MetricViewSwitch({
    view,
    onChange,
}: {
    view: MetricView
    onChange: (view: MetricView) => void
}): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-2">
            <Text size="xs" variant="muted">
                Show results as
            </Text>
            <ToggleGroup
                variant="outline"
                size="sm"
                value={[view]}
                onValueChange={(value: string[]) => value[0] && onChange(value[0] as MetricView)}
                aria-label="Show results as"
                data-attr="metric-view"
                className="flex-wrap"
            >
                {VIEW_OPTIONS.map((option) => (
                    <ToggleGroupItem key={option.value} value={option.value}>
                        {option.icon}
                        {option.label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
            <Text size="xs" variant="muted">
                {VIEW_OPTIONS.find((option) => option.value === view)?.hint}
            </Text>
        </div>
    )
}

export function isSignificant(variant: PrototypeVariantResult): boolean {
    return variant.interval !== null && (variant.interval[0] > 0 || variant.interval[1] < 0)
}

/** A drop is a win when the metric's goal is "decrease", so color by goal, not by the delta's sign. */
export function isWin(variant: PrototypeVariantResult, goal: MetricGoal | undefined): boolean {
    const delta = variant.delta ?? 0
    return goal === METRIC_GOAL.decrease ? delta < 0 : delta > 0
}

export function formatPercent(value: number): string {
    return `${value > 0 ? '+' : ''}${Math.round(value * 100)}%`
}

export function formatDelta(value: number): string {
    return `${value > 0 ? '+' : ''}${(value * 100).toFixed(1)}%`
}

/** Ratio of the 50% to the 95% half width of a normal interval, so the box shows where the delta most likely is. */
export const HALF_INTERVAL_RATIO = 0.674 / 1.96

/** One horizontal box per variant: whiskers are the 95% interval, the box is the 50% interval, the line is the delta. */
export function CandlestickChart({ metric, height }: { metric: PrototypeMetric; height: number }): JSX.Element {
    const theme = useChartTheme()
    const labels = metric.variants.map((variant) => variant.key)
    const series: BoxPlotSeries[] = useMemo(
        () => [
            {
                key: 'delta',
                label: 'Delta',
                data: metric.variants.map((variant) => {
                    if (variant.delta === null || variant.interval === null) {
                        /** Control is the baseline, drawn as a point at 0% so every chart shows where zero is. */
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
                }),
            },
        ],
        [metric]
    )
    return (
        <div className="flex flex-col" style={{ height }}>
            <BoxPlot
                series={series}
                labels={labels}
                theme={theme}
                config={{
                    axisOrientation: 'horizontal',
                    showGrid: true,
                    yTickFormatter: formatPercent,
                    hideYAxis: true,
                    margins: { left: 8, right: 16, top: 4, bottom: 20 },
                }}
            >
                <ReferenceLine value={0} orientation="vertical" variant="marker" showValueOnHover={false} />
            </BoxPlot>
        </div>
    )
}

/** Every metric and variant on one delta over time chart. Color is the metric; a dashed line is the second variant. */
export function AllMetricsTrendChart({ metrics, limit }: { metrics: PrototypeMetric[]; limit: number }): JSX.Element {
    const theme = useChartTheme()
    const series: Series[] = useMemo(
        () =>
            metrics.flatMap((metric, metricIndex) =>
                metricTrends(metric).map((trend, trendIndex) => ({
                    key: `${metric.name}-${trend.key}`,
                    label: `${metric.name} · ${trend.key}`,
                    data: trend.delta,
                    color: theme.colors[metricIndex % theme.colors.length],
                    stroke: { width: 1.75, pattern: trendIndex === 0 ? [5, 4] : undefined },
                }))
            ),
        [metrics, theme]
    )
    const config: LineChartConfig = useMemo(
        () => ({
            curve: 'monotone',
            showGrid: true,
            valueDomain: { min: -limit, max: limit },
            yTickFormatter: formatPercent,
            xTickFormatter: (label: string) => dayjs(label).format('MMM D'),
            margins: { left: 40 },
        }),
        [limit]
    )
    const variantKeys = metrics[0].variants.filter((variant) => variant.delta !== null).map((variant) => variant.key)
    return (
        <div className="flex flex-col gap-2">
            <div className="flex h-64 flex-col">
                <LineChart series={series} labels={EXPOSURES.days} theme={theme} config={config}>
                    <ReferenceLine value={0} orientation="horizontal" variant="marker" showValueOnHover={false} />
                </LineChart>
            </div>
            {/* Color names the metric and the line style names the variant, so six lines need only five keys. */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 pl-10">
                {metrics.map((metric, index) => (
                    <span key={metric.name} className="flex items-center gap-1.5">
                        <span
                            className="h-0.5 w-4 rounded-full"
                            style={{ background: theme.colors[index % theme.colors.length] }}
                        />
                        <Text size="xs">{metric.name}</Text>
                    </span>
                ))}
                <span className="h-3 w-px bg-border" />
                {variantKeys.map((key, index) => (
                    <span key={key} className="flex items-center gap-1.5">
                        <span
                            className={
                                index === 0
                                    ? 'w-4 border-t-2 border-dashed border-muted-foreground'
                                    : 'w-4 border-t-2 border-muted-foreground'
                            }
                        />
                        <Text size="xs" className="font-mono">
                            {key}
                        </Text>
                    </span>
                ))}
            </div>
        </div>
    )
}

const MATRIX_TOKENS = ['success-foreground', 'destructive-foreground', 'muted-foreground'] as const
export type MatrixToken = (typeof MATRIX_TOKENS)[number]

/**
 * The chart resolves `var(--…)` against the document root, but quill tokens live under `[data-quill]`,
 * and the heatmap ramp cannot parse oklch. So read each token from inside the card and paint it once
 * to get plain rgb.
 */
export function useResolvedTokens(): [React.RefObject<HTMLDivElement>, Record<MatrixToken, string> | null] {
    const ref = useRef<HTMLDivElement>(null)
    const [colors, setColors] = useState<Record<MatrixToken, string> | null>(null)
    useEffect(() => {
        const element = ref.current
        const context = document.createElement('canvas').getContext('2d', { willReadFrequently: true })
        if (!element || !context) {
            return
        }
        const resolved = Object.fromEntries(
            MATRIX_TOKENS.map((token) => {
                const value = getComputedStyle(element).getPropertyValue(`--${token}`).trim()
                context.clearRect(0, 0, 1, 1)
                context.fillStyle = value
                context.fillRect(0, 0, 1, 1)
                const [red, green, blue] = context.getImageData(0, 0, 1, 1).data
                return [token, `rgb(${red}, ${green}, ${blue})`]
            })
        ) as Record<MatrixToken, string>
        setColors(resolved)
    }, [])
    return [ref, colors]
}

/** Metrics down, variants across. A significant gain is green, a significant loss is red, the rest is gray. */
export function MetricMatrix({ metrics }: { metrics: PrototypeMetric[] }): JSX.Element {
    const theme = useChartTheme()
    const [ref, tokens] = useResolvedTokens()
    const variantKeys = metrics[0].variants.filter((variant) => variant.delta !== null).map((variant) => variant.key)
    /** The heatmap draws its first row at the bottom, so reverse the metrics to read top down. */
    const rows = [...metrics].reverse()
    const lookup = (rowIndex: number, variantKey: string): PrototypeVariantResult | undefined =>
        rows[rowIndex].variants.find((variant) => variant.key === variantKey)
    const cells = rows.map((metric) =>
        variantKeys.map((key) => {
            const variant = metric.variants.find((item) => item.key === key)
            return variant?.delta ? Math.abs(variant.delta) * 100 : 0
        })
    )
    return (
        <div ref={ref} className="flex flex-col" style={{ height: metrics.length * 44 + 36 }}>
            {tokens && (
                <Heatmap
                    xLabels={variantKeys}
                    yLabels={rows.map((metric) => `${metrics.indexOf(metric) + 1}. ${metric.name}`)}
                    cells={cells}
                    theme={theme}
                    config={{
                        colorScale: 'linear',
                        cellLabel: (cell: HeatmapCellDatum) => {
                            const variant = lookup(cell.yIndex, cell.xLabel)
                            if (!variant || variant.delta === null) {
                                return null
                            }
                            return `${formatDelta(variant.delta)} · ${Math.round((variant.chanceToWin ?? 0) * 100)}%`
                        },
                        cellStyle: (cell: HeatmapCellDatum) => {
                            const variant = lookup(cell.yIndex, cell.xLabel)
                            if (!variant || !isSignificant(variant)) {
                                return { color: tokens['muted-foreground'], filled: true }
                            }
                            return {
                                color: isWin(variant, rows[cell.yIndex].goal)
                                    ? tokens['success-foreground']
                                    : tokens['destructive-foreground'],
                                filled: true,
                            }
                        },
                        margins: { left: 150 },
                    }}
                />
            )}
        </div>
    )
}

interface EffectPointMeta {
    metric: string
    variant: string
    significant: boolean
}

/** One point per metric and variant: how big the change is against how sure the result is. Top right is a win. */
export function EffectMap({
    metrics,
    colors,
}: {
    metrics: PrototypeMetric[]
    colors: Record<string, string>
}): JSX.Element {
    const theme = useChartTheme()
    const variantKeys = metrics[0].variants.filter((variant) => variant.delta !== null).map((variant) => variant.key)
    const limit = Math.max(
        0.05,
        ...metrics.flatMap((metric) => metric.variants.map((variant) => Math.abs(variant.delta ?? 0)))
    )
    const series: ScatterSeries<EffectPointMeta>[] = variantKeys.map((key) => ({
        key,
        label: key,
        color: colors[key],
        points: metrics.flatMap((metric) => {
            const variant = metric.variants.find((item) => item.key === key)
            if (!variant || variant.delta === null || variant.chanceToWin === null) {
                return []
            }
            const significant = isSignificant(variant)
            return [
                {
                    x: variant.delta,
                    y: variant.chanceToWin,
                    label: `${metric.name} · ${key}`,
                    radius: significant ? 7 : 4.5,
                    meta: { metric: metric.name, variant: key, significant },
                },
            ]
        }),
    }))
    return (
        <div className="flex h-72 flex-col">
            <ScatterChart
                series={series}
                theme={theme}
                config={{
                    xAxis: {
                        domain: [-limit * 1.2, limit * 1.2],
                        label: 'Delta',
                        tickFormatter: formatPercent,
                    },
                    yAxis: {
                        domain: [0, 1],
                        label: 'Chance to win',
                        tickFormatter: (value: number) => `${Math.round(value * 100)}%`,
                    },
                    showGrid: true,
                    fillOpacity: 0.85,
                    legend: { show: true, position: 'bottom', align: 'start' },
                    tooltip: {
                        xFormatter: (value: number) => formatDelta(value),
                        yFormatter: (value: number) => `${Math.round(value * 100)}% chance to win`,
                    },
                }}
            />
        </div>
    )
}

/** The chart a section shows above its table, for the views that draw one chart for all metrics. */
export function SectionChart({
    view,
    title,
    metrics,
    colors,
    limit,
}: {
    view: MetricView
    title: string
    metrics: PrototypeMetric[]
    colors: Record<string, string>
    limit: number
}): JSX.Element | null {
    if (!SECTION_CHART_VIEWS.includes(view)) {
        return null
    }
    const caption = {
        'one-chart': `Delta over time for every ${title.toLowerCase().replace(' metrics', '')} metric. Hover the chart for each value.`,
        matrix: 'Each cell shows the delta and the chance to win. Color shows a significant change; gray is not significant.',
        'effect-map': 'Right is a gain, top is more certain. Large points are significant.',
    }[view as 'one-chart' | 'matrix' | 'effect-map']
    return (
        <Card size="sm" className="mb-3 gap-2" data-attr={`metric-section-chart-${view}`}>
            <Text size="xs" variant="muted">
                {caption}
            </Text>
            {view === METRIC_VIEW.oneChart && <AllMetricsTrendChart metrics={metrics} limit={limit} />}
            {view === METRIC_VIEW.matrix && <MetricMatrix metrics={metrics} />}
            {view === METRIC_VIEW.effectMap && <EffectMap metrics={metrics} colors={colors} />}
        </Card>
    )
}
