import { Circle, Path, RoundedRect, Skia, Line as SkiaLine, vec } from '@shopify/react-native-skia'
import { type ReactElement, useMemo } from 'react'
import type { ComposedGesture } from 'react-native-gesture-handler'
import { type SharedValue, useDerivedValue } from 'react-native-reanimated'
import {
    Area,
    CartesianChart,
    type ChartBounds,
    type ChartPressState,
    Line,
    type PointsArray,
    type Scale,
} from 'victory-native'

import { colors } from '@/ui/tokens'

import { BAR_BAND_PADDING, BAR_MIN_HEIGHT } from './chartMath'
import { GESTURE_CONFIG, PRESS_CONFIG } from './gestures/useChartGestures'
import type { ChartKind } from './types'

export interface Datum extends Record<string, unknown> {
    index: number
    value: number | null
}

export interface Gridlines {
    tickValues: number[]
    tickCount: number
    domain: [number, number]
    lineColor: string
    lineWidth: number
    font: null
}

const AREA_OPACITY = 0.08
const DOT_RADIUS = 4
const Y_KEYS: 'value'[] = ['value']

interface MetricChartRendererProps {
    data: Datum[]
    kind: ChartKind
    color: string
    width: number
    height: number
    padding: { left: number; right: number; top: number; bottom: number }
    domain: { x: [number, number]; y: [number, number] }
    gridlines: Gridlines[]
    pressState: ChartPressState<{ x: number; y: { value: number } }>
    gestures: ComposedGesture
    selected: SharedValue<number>
    xs: number[]
    ys: number[]
    onScaleChange: (x: Scale, y: Scale) => void
}

/** Draws the plot: gridlines, the line or bars, and the selection marker. Overlays live in `MetricChartCanvas`. */
export function MetricChartRenderer({
    data,
    kind,
    color,
    width,
    height,
    padding,
    domain,
    gridlines,
    pressState,
    gestures,
    selected,
    xs,
    ys,
    onScaleChange,
}: MetricChartRendererProps): ReactElement {
    return (
        <CartesianChart
            data={data}
            xKey="index"
            yKeys={Y_KEYS}
            explicitSize={{ width, height }}
            padding={padding}
            domain={domain}
            yAxis={gridlines}
            chartPressState={pressState}
            chartPressConfig={PRESS_CONFIG}
            customGestures={gestures}
            gestureHandlerConfig={GESTURE_CONFIG}
            onScaleChange={onScaleChange}
            renderOutside={({ chartBounds }) => (
                <>
                    <SkiaLine
                        p1={vec(chartBounds.left, chartBounds.bottom)}
                        p2={vec(chartBounds.right, chartBounds.bottom)}
                        color={colors.border}
                        strokeWidth={1}
                    />
                    {kind === 'line' ? (
                        <LineSelection selected={selected} xs={xs} ys={ys} bounds={chartBounds} color={color} />
                    ) : null}
                </>
            )}
        >
            {({ points: series, chartBounds }) =>
                kind === 'line' ? (
                    <>
                        <Area points={series.value} y0={chartBounds.bottom} color={color} opacity={AREA_OPACITY} />
                        <Line points={series.value} color={color} strokeWidth={2} />
                    </>
                ) : (
                    <Bars
                        points={series.value}
                        bounds={chartBounds}
                        count={data.length}
                        selected={selected}
                        xs={xs}
                        ys={ys}
                        color={color}
                    />
                )
            }
        </CartesianChart>
    )
}

interface SelectionProps {
    selected: SharedValue<number>
    xs: number[]
    ys: number[]
    bounds: ChartBounds
    color: string
}

function LineSelection({ selected, xs, ys, bounds, color }: SelectionProps): ReactElement {
    const x = useDerivedValue(() => xs[selected.value] ?? 0)
    const y = useDerivedValue(() => ys[selected.value] ?? 0)
    const opacity = useDerivedValue(() => (selected.value >= 0 && Number.isFinite(ys[selected.value]) ? 1 : 0))
    const top = useDerivedValue(() => vec(x.value, bounds.top))
    const bottom = useDerivedValue(() => vec(x.value, bounds.bottom))
    return (
        <>
            <SkiaLine p1={top} p2={bottom} color={colors.border} strokeWidth={1} opacity={opacity} />
            <Circle cx={x} cy={y} r={DOT_RADIUS + 1.5} color={colors.white} opacity={opacity} />
            <Circle cx={x} cy={y} r={DOT_RADIUS} color={color} opacity={opacity} />
        </>
    )
}

interface BarsProps extends SelectionProps {
    points: PointsArray
    count: number
}

function Bars({ points, bounds, count, selected, xs, ys, color }: BarsProps): ReactElement {
    const barWidth = ((bounds.right - bounds.left) / Math.max(1, count)) * (1 - BAR_BAND_PADDING)
    const path = useMemo(() => {
        const builder = Skia.PathBuilder.Make()
        for (const point of points) {
            if (typeof point.y !== 'number' || !Number.isFinite(point.y)) {
                continue
            }
            const top = Math.min(point.y, bounds.bottom - BAR_MIN_HEIGHT)
            const rect = Skia.XYWHRect(point.x - barWidth / 2, top, barWidth, bounds.bottom - top)
            builder.addRRect(Skia.RRectXY(rect, 1, 1))
        }
        return builder.detach()
    }, [points, bounds.bottom, barWidth])

    const x = useDerivedValue(() => (xs[selected.value] ?? 0) - barWidth / 2)
    const y = useDerivedValue(() => Math.min(ys[selected.value] ?? bounds.bottom, bounds.bottom - BAR_MIN_HEIGHT))
    const barHeight = useDerivedValue(() => bounds.bottom - y.value)
    const opacity = useDerivedValue(() => (selected.value >= 0 && Number.isFinite(ys[selected.value]) ? 1 : 0))

    return (
        <>
            <Path path={path} color={colors.border} />
            <RoundedRect x={x} y={y} width={barWidth} height={barHeight} r={1} color={color} opacity={opacity} />
        </>
    )
}
