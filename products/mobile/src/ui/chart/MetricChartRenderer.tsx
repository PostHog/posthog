import {
    Circle,
    DashPathEffect,
    Path,
    Rect,
    RoundedRect,
    Skia,
    Line as SkiaLine,
    vec,
} from '@shopify/react-native-skia'
import { type ReactElement, useMemo } from 'react'
import type { ComposedGesture } from 'react-native-gesture-handler'
import { type SharedValue, useDerivedValue } from 'react-native-reanimated'
import { Area, CartesianChart, Line, type PointsArray } from 'victory-native'

import { colors } from '@/ui/tokens'

import type { ChartGeometry, PlotRect } from './chartGeometry'
import { BAR_BAND_PADDING, BAR_MIN_HEIGHT } from './chartMath'
import { gestureHandlerConfig } from './gestures/useChartGestures'
import type { ChartSelectionValues } from './selection/useChartSelection'
import type { ChartKind, ChartVariant } from './types'

/** One visible series in canvas coordinates. */
export interface PlottedSeries {
    key: string
    color: string
    dotted: boolean
    compare: boolean
    points: PointsArray
    /** The y of each bucket, NaN for a gap. */
    ys: number[]
    incompleteFrom?: number
}

const AREA_OPACITY = 0.08
const RANGE_OPACITY = 0.08
const DOT_RADIUS = 4.5
const PREVIOUS_DOT_RADIUS = 3
const DOT_RING = 1.5
const INCOMPLETE_DASH = [3, 4]
const PREVIOUS_DASH = [5, 4]
const Y_KEYS: 'v'[] = ['v']
// victory-native draws default gridlines unless told not to; this renderer draws its own from `geometry`.
const NO_Y_AXIS = [{ lineWidth: 0, tickCount: 0, font: null }]

interface MetricChartRendererProps {
    geometry: ChartGeometry
    kind: ChartKind
    variant: ChartVariant
    series: PlottedSeries[]
    /** The highlight color of a single-series bar chart. */
    accent: string
    selection: ChartSelectionValues
    gestures: ComposedGesture
}

/**
 * Draws only. victory-native hosts the canvas and the gesture view; every coordinate comes from `geometry`, which the
 * canvas computes during render, so the drawing never waits for victory's scales.
 */
export function MetricChartRenderer({
    geometry,
    kind,
    variant,
    series,
    accent,
    selection,
    gestures,
}: MetricChartRendererProps): ReactElement {
    const { width, height, plot, xs } = geometry
    const count = xs.length
    // victory-native recomputes its layout when these props change identity, so they are memoized.
    const data = useMemo(() => Array.from({ length: Math.max(1, count) }, (_, index) => ({ index, v: 0 })), [count])
    const padding = useMemo(
        () => ({ left: plot.left, right: width - plot.right, top: plot.top, bottom: height - plot.bottom }),
        [plot, width, height]
    )
    const domain = useMemo(
        () => ({ x: [0, Math.max(1, count - 1)] as [number, number], y: [0, 1] as [number, number] }),
        [count]
    )
    const handlerConfig = useMemo(() => gestureHandlerConfig(variant), [variant])
    const current = series.filter((s) => !s.compare)

    return (
        <CartesianChart
            data={data}
            xKey="index"
            yKeys={Y_KEYS}
            explicitSize={{ width, height }}
            padding={padding}
            domain={domain}
            yAxis={NO_Y_AXIS}
            customGestures={gestures}
            gestureHandlerConfig={handlerConfig}
            renderOutside={() => (
                <>
                    {geometry.yTicks.map((tick) => (
                        <SkiaLine
                            key={tick.value}
                            p1={vec(plot.left, tick.y)}
                            p2={vec(plot.right, tick.y)}
                            color={colors.hairline}
                            strokeWidth={1}
                        />
                    ))}
                    <SkiaLine
                        p1={vec(plot.left, plot.bottom)}
                        p2={vec(plot.right, plot.bottom)}
                        color={colors.border}
                        strokeWidth={1}
                    />
                    <RangeShade selection={selection} xs={xs} plot={plot} />
                    {kind === 'bar' ? (
                        <Bars series={current} geometry={geometry} accent={accent} selection={selection} />
                    ) : (
                        <Lines series={series} plot={plot} />
                    )}
                    {kind === 'line' ? <Markers series={series} xs={xs} plot={plot} selection={selection} /> : null}
                </>
            )}
        >
            {() => null}
        </CartesianChart>
    )
}

function Lines({ series, plot }: { series: PlottedSeries[]; plot: PlotRect }): ReactElement {
    const current = series.filter((s) => !s.compare)
    const only = current.length === 1 ? current[0] : undefined
    return (
        <>
            {only ? <Area points={only.points} y0={plot.bottom} color={only.color} opacity={AREA_OPACITY} /> : null}
            {series.map((s) => (
                <SeriesLine key={s.key} series={s} />
            ))}
        </>
    )
}

function SeriesLine({ series }: { series: PlottedSeries }): ReactElement {
    const { points, color, dotted, incompleteFrom } = series
    const split = incompleteFrom !== undefined && incompleteFrom < points.length && !dotted
    const solid = useMemo(
        () => (split ? points.slice(0, Math.max(0, incompleteFrom)) : points),
        [points, split, incompleteFrom]
    )
    const dashed = useMemo(
        () => (split ? points.slice(Math.max(0, (incompleteFrom ?? 0) - 1)) : []),
        [points, split, incompleteFrom]
    )
    return (
        <>
            <Line points={solid} color={color} strokeWidth={2} strokeCap="round" strokeJoin="round">
                {dotted ? <DashPathEffect intervals={PREVIOUS_DASH} /> : null}
            </Line>
            {split ? (
                <Line points={dashed} color={color} strokeWidth={2} strokeCap="round" strokeJoin="round">
                    <DashPathEffect intervals={INCOMPLETE_DASH} />
                </Line>
            ) : null}
        </>
    )
}

function RangeShade({
    selection,
    xs,
    plot,
}: {
    selection: ChartSelectionValues
    xs: number[]
    plot: PlotRect
}): ReactElement {
    const { selA, selB } = selection
    const x = useDerivedValue(() => Math.min(xs[selA.value] ?? 0, xs[selB.value] ?? 0))
    const width = useDerivedValue(() => Math.abs((xs[selA.value] ?? 0) - (xs[selB.value] ?? 0)))
    const opacity = useDerivedValue(() => (selA.value >= 0 && selB.value >= 0 ? RANGE_OPACITY : 0))
    return (
        <Rect x={x} y={plot.top} width={width} height={plot.bottom - plot.top} color={colors.blue} opacity={opacity} />
    )
}

function Markers({
    series,
    xs,
    plot,
    selection,
}: {
    series: PlottedSeries[]
    xs: number[]
    plot: PlotRect
    selection: ChartSelectionValues
}): ReactElement {
    return (
        <>
            <Marker sel={selection.selA} series={series} xs={xs} plot={plot} />
            <Marker sel={selection.selB} series={series} xs={xs} plot={plot} />
        </>
    )
}

function Marker({
    sel,
    series,
    xs,
    plot,
}: {
    sel: SharedValue<number>
    series: PlottedSeries[]
    xs: number[]
    plot: PlotRect
}): ReactElement {
    const x = useDerivedValue(() => xs[sel.value] ?? 0)
    const top = useDerivedValue(() => vec(x.value, plot.top))
    const bottom = useDerivedValue(() => vec(x.value, plot.bottom))
    const opacity = useDerivedValue(() => (sel.value >= 0 ? 1 : 0))
    return (
        <>
            <SkiaLine p1={top} p2={bottom} color={colors.ink} strokeWidth={1} opacity={opacity} />
            {series.map((s) => (
                <Dot key={s.key} sel={sel} x={x} series={s} />
            ))}
        </>
    )
}

function Dot({
    sel,
    x,
    series,
}: {
    sel: SharedValue<number>
    x: SharedValue<number>
    series: PlottedSeries
}): ReactElement {
    const { ys } = series
    const y = useDerivedValue(() => ys[sel.value] ?? 0)
    const opacity = useDerivedValue(() => (sel.value >= 0 && Number.isFinite(ys[sel.value]) ? 1 : 0))
    const radius = series.compare ? PREVIOUS_DOT_RADIUS : DOT_RADIUS
    return (
        <>
            <Circle cx={x} cy={y} r={radius + DOT_RING} color={colors.white} opacity={opacity} />
            <Circle cx={x} cy={y} r={radius} color={series.color} opacity={opacity} />
        </>
    )
}

function Bars({
    series,
    geometry,
    accent,
    selection,
}: {
    series: PlottedSeries[]
    geometry: ChartGeometry
    accent: string
    selection: ChartSelectionValues
}): ReactElement {
    const { plot, bandWidth } = geometry
    const single = series.length === 1
    const groupWidth = bandWidth * (1 - BAR_BAND_PADDING)
    const barWidth = groupWidth / Math.max(1, series.length)
    const paths = useMemo(
        () =>
            series.map((s, seriesIndex) => {
                const builder = Skia.PathBuilder.Make()
                for (const point of s.points) {
                    if (typeof point.y !== 'number' || !Number.isFinite(point.y)) {
                        continue
                    }
                    const top = Math.min(point.y, plot.bottom - BAR_MIN_HEIGHT)
                    const left = point.x - groupWidth / 2 + seriesIndex * barWidth
                    builder.addRRect(Skia.RRectXY(Skia.XYWHRect(left, top, barWidth, plot.bottom - top), 1, 1))
                }
                // A single series draws gray and highlights the selected bar; several keep their colors.
                return { key: s.key, path: builder.detach(), color: single ? colors.border : s.color }
            }),
        [series, plot.bottom, groupWidth, barWidth, single]
    )
    const first = series[0]
    return (
        <>
            {paths.map(({ key, path, color }) => (
                <Path key={key} path={path} color={color} />
            ))}
            {single && first ? (
                <>
                    <BarHighlight
                        sel={selection.selA}
                        series={first}
                        xs={geometry.xs}
                        plot={plot}
                        width={barWidth}
                        color={accent}
                    />
                    <BarHighlight
                        sel={selection.selB}
                        series={first}
                        xs={geometry.xs}
                        plot={plot}
                        width={barWidth}
                        color={accent}
                    />
                </>
            ) : (
                <Markers series={[]} xs={geometry.xs} plot={plot} selection={selection} />
            )}
        </>
    )
}

function BarHighlight({
    sel,
    series,
    xs,
    plot,
    width,
    color,
}: {
    sel: SharedValue<number>
    series: PlottedSeries
    xs: number[]
    plot: PlotRect
    width: number
    color: string
}): ReactElement {
    const { ys } = series
    const x = useDerivedValue(() => (xs[sel.value] ?? 0) - width / 2)
    const y = useDerivedValue(() => Math.min(ys[sel.value] ?? plot.bottom, plot.bottom - BAR_MIN_HEIGHT))
    const barHeight = useDerivedValue(() => plot.bottom - y.value)
    const opacity = useDerivedValue(() => (sel.value >= 0 && Number.isFinite(ys[sel.value]) ? 1 : 0))
    return <RoundedRect x={x} y={y} width={width} height={barHeight} r={1} color={color} opacity={opacity} />
}
