import { Circle, Path, RoundedRect, Skia, Line as SkiaLine, vec } from '@shopify/react-native-skia'
import { type ReactElement, useCallback, useMemo, useRef, useState } from 'react'
import { type LayoutChangeEvent, StyleSheet, Text, View } from 'react-native'
import { Gesture } from 'react-native-gesture-handler'
import { type SharedValue, useAnimatedReaction, useDerivedValue } from 'react-native-reanimated'
import { scheduleOnRN } from 'react-native-worklets'
import {
    Area,
    CartesianChart,
    type ChartBounds,
    Line,
    type PointsArray,
    type Scale,
    useChartPressState,
} from 'victory-native'

import { haptic } from '@/lib/haptics'
import { accentColor, colors, fonts, lineHeight } from '@/ui/tokens'
import { ChartTooltip } from './ChartTooltip'
import {
    BAR_BAND_PADDING,
    BAR_MIN_HEIGHT,
    CHART_DEFAULT_HEIGHT,
    formatAxisDate,
    formatTooltipDate,
    monoTextWidth,
    nearestIndex,
    samePoints,
    snapToValue,
    TICK_FONT_SIZE,
    TICK_GAP,
    tooltipLeft,
    xTickIndices,
    yAxisTicks,
} from './chartMath'
import type { ChartPoint, MetricChartProps } from './types'

interface Datum extends Record<string, unknown> {
    index: number
    value: number | null
}

interface Scales {
    x: Scale
    y: Scale
}

const TICK_LINE_HEIGHT = lineHeight(TICK_FONT_SIZE)
const PLOT_TOP = Math.ceil(TICK_LINE_HEIGHT / 2)
const X_LABEL_OFFSET = 6
const PLOT_BOTTOM = Math.ceil(TICK_LINE_HEIGHT) + X_LABEL_OFFSET
const X_LABEL_SLACK = 8
const TOOLTIP_GAP = 12
const AREA_OPACITY = 0.08
const DOT_RADIUS = 4
// A drag scrubs once it moves 8pt sideways, and a 10pt vertical move first hands the touch to the surrounding
// ScrollView. Victory's default instead waits for a 100ms long press, which makes scrubbing feel slow.
const PRESS_CONFIG = { pan: { activeOffsetX: [-8, 8] as [number, number], failOffsetY: [-10, 10] as [number, number] } }
// On web, the browser keeps vertical touch scrolling while the chart takes horizontal drags.
const GESTURE_CONFIG = { touchAction: 'pan-y' } as const
const Y_KEYS: 'value'[] = ['value']
const TAP_MAX_DISTANCE = 10

/** Keeps the previous array when a parent passes an equal one, so re-renders do not clear the selection. */
function useStablePoints(points: ChartPoint[]): ChartPoint[] {
    const stable = useRef(points)
    if (!samePoints(stable.current, points)) {
        stable.current = points
    }
    return stable.current
}

export function MetricChartCanvas({
    points: rawPoints,
    kind,
    interval,
    accent,
    label,
    formatValue,
    height = CHART_DEFAULT_HEIGHT,
    onSelect,
    testID,
}: MetricChartProps): ReactElement {
    const points = useStablePoints(rawPoints)
    const color = accentColor[accent]
    const [width, setWidth] = useState(0)
    const [scales, setScales] = useState<Scales | null>(null)
    const [selectedIndex, setSelectedIndex] = useState(-1)
    const [tooltipWidth, setTooltipWidth] = useState(0)
    const lastIndex = useRef(-1)
    // victory-native resets its press state when `data` changes; the JS mirror of it resets here, during render.
    const [selectionPoints, setSelectionPoints] = useState(points)
    if (selectionPoints !== points) {
        setSelectionPoints(points)
        setSelectedIndex(-1)
        lastIndex.current = -1
    }

    const data = useMemo<Datum[]>(
        () => points.map((point, index) => ({ index, value: Number.isFinite(point.value) ? point.value : null })),
        [points]
    )
    const values = useMemo(() => points.map((point) => point.value), [points])
    const yAxis = useMemo(() => {
        const { domain, ticks } = yAxisTicks(values, kind)
        return { domain, ticks: ticks.map((tick) => ({ tick, text: formatValue(tick) })) }
    }, [values, kind, formatValue])

    const yLabelWidth = Math.max(0, ...yAxis.ticks.map(({ text }) => monoTextWidth(text)))
    const plotWidth = Math.max(0, width - yLabelWidth - TICK_GAP)
    // victory-native recomputes its layout when these props change identity, so they are memoized.
    const padding = useMemo(
        () => ({ left: yLabelWidth + TICK_GAP, right: 0, top: PLOT_TOP, bottom: PLOT_BOTTOM }),
        [yLabelWidth]
    )
    const domain = useMemo(() => {
        // Bars sit in the middle of equal slots; a line runs from edge to edge.
        const x: [number, number] =
            kind === 'bar' ? [-0.5, Math.max(0.5, points.length - 0.5)] : [0, Math.max(1, points.length - 1)]
        return { x, y: yAxis.domain }
    }, [kind, points.length, yAxis.domain])
    const gridlines = useMemo(
        () => [
            {
                tickValues: yAxis.ticks.map(({ tick }) => tick),
                tickCount: yAxis.ticks.length,
                domain: yAxis.domain,
                lineColor: colors.hairline,
                lineWidth: 1,
                font: null,
            },
        ],
        [yAxis]
    )

    const xLabels = useMemo(() => {
        const texts = points.map((point) => formatAxisDate(point.at, interval))
        const labelWidth = Math.max(0, ...texts.map((text) => monoTextWidth(text)))
        return xTickIndices(points.length, plotWidth, labelWidth).map((index) => ({ index, text: texts[index] ?? '' }))
    }, [points, interval, plotWidth])

    const xs = useMemo(() => (scales ? data.map((datum) => scales.x(datum.index)) : []), [scales, data])
    const ys = useMemo(
        () => (scales ? data.map((datum) => (datum.value === null ? Number.NaN : scales.y(datum.value))) : []),
        [scales, data]
    )

    const { state } = useChartPressState({ x: 0, y: { value: 0 } })
    const selected = useDerivedValue(() => snapToValue(values, state.matchedIndex.value))

    const emitSelection = useCallback(
        (index: number, pressStarted: boolean): void => {
            const changed = index !== lastIndex.current
            lastIndex.current = index
            setSelectedIndex(index)
            const point = points[index]
            if (!point) {
                if (changed) {
                    onSelect?.(null)
                }
                return
            }
            if (changed) {
                haptic('selection')
            }
            if (changed || pressStarted) {
                onSelect?.(point)
            }
        },
        [points, onSelect]
    )

    const emitRelease = useCallback((): void => onSelect?.(null), [onSelect])

    // A tap selects on the JS thread first, so the reaction below sees no change and does not report the point twice.
    const selectByTap = useCallback(
        (index: number): void => {
            emitSelection(index, true)
            state.matchedIndex.value = index
            emitRelease()
        },
        [emitSelection, emitRelease, state]
    )

    useAnimatedReaction(
        () => ({ index: selected.value, active: state.isActive.value }),
        (current, previous) => {
            if (previous === null) {
                return
            }
            const started = current.active && !previous.active
            if (current.index !== previous.index || started) {
                scheduleOnRN(emitSelection, current.index, started)
            } else if (previous.active && !current.active) {
                scheduleOnRN(emitRelease)
            }
        },
        [emitSelection, emitRelease]
    )

    const tap = useMemo(
        () =>
            Gesture.Tap()
                .maxDistance(TAP_MAX_DISTANCE)
                .onEnd((event, success) => {
                    if (!success) {
                        return
                    }
                    const index = nearestIndex(xs, event.x)
                    if (index >= 0) {
                        scheduleOnRN(selectByTap, index)
                    }
                }),
        [xs, selectByTap]
    )
    const customGestures = useMemo(() => Gesture.Race(tap), [tap])

    const onLayout = useCallback((event: LayoutChangeEvent): void => {
        setWidth(Math.round(event.nativeEvent.layout.width))
    }, [])
    const onScaleChange = useCallback((x: Scale, y: Scale): void => setScales({ x, y }), [])

    const selectedPoint = points[selectedIndex]
    const anchorX = xs[selectedIndex]
    const latest = [...points].reverse().find((point) => Number.isFinite(point.value))

    return (
        <View
            style={[styles.container, { height }]}
            onLayout={onLayout}
            testID={testID}
            accessibilityRole="image"
            accessibilityLabel={latest ? `${label} chart, latest ${formatValue(latest.value)}` : `${label} chart`}
        >
            {width > 0 ? (
                <CartesianChart
                    data={data}
                    xKey="index"
                    yKeys={Y_KEYS}
                    explicitSize={{ width, height }}
                    padding={padding}
                    domain={domain}
                    yAxis={gridlines}
                    chartPressState={state}
                    chartPressConfig={PRESS_CONFIG}
                    customGestures={customGestures}
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
                                <Area
                                    points={series.value}
                                    y0={chartBounds.bottom}
                                    color={color}
                                    opacity={AREA_OPACITY}
                                />
                                <Line points={series.value} color={color} strokeWidth={2} />
                            </>
                        ) : (
                            <Bars
                                points={series.value}
                                bounds={chartBounds}
                                count={points.length}
                                selected={selected}
                                xs={xs}
                                ys={ys}
                                color={color}
                            />
                        )
                    }
                </CartesianChart>
            ) : null}
            {scales
                ? yAxis.ticks.map(({ tick, text }) => (
                      <Text
                          key={`y-${tick}`}
                          numberOfLines={1}
                          style={[
                              styles.tick,
                              { right: width - yLabelWidth, top: scales.y(tick) - TICK_LINE_HEIGHT / 2 },
                          ]}
                      >
                          {text}
                      </Text>
                  ))
                : null}
            {scales
                ? xLabels.map(({ index, text }) => {
                      // Wider than the text, so a small error in the width estimate cannot wrap or truncate it.
                      const labelWidth = monoTextWidth(text) + X_LABEL_SLACK
                      const center = scales.x(index)
                      const left = Math.min(width - labelWidth, Math.max(0, center - labelWidth / 2))
                      return (
                          <Text
                              key={`x-${index}`}
                              numberOfLines={1}
                              style={[
                                  styles.tick,
                                  styles.xTick,
                                  { left, width: labelWidth, top: height - PLOT_BOTTOM + X_LABEL_OFFSET },
                              ]}
                          >
                              {text}
                          </Text>
                      )
                  })
                : null}
            {selectedPoint && anchorX !== undefined && Number.isFinite(selectedPoint.value) ? (
                <ChartTooltip
                    title={formatTooltipDate(selectedPoint.at, interval)}
                    label={label}
                    value={formatValue(selectedPoint.value)}
                    color={color}
                    left={tooltipLeft(anchorX, tooltipWidth, width, TOOLTIP_GAP)}
                    top={0}
                    onLayout={(event) => setTooltipWidth(event.nativeEvent.layout.width)}
                    testID={testID ? `${testID}-tooltip` : undefined}
                />
            ) : null}
        </View>
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

const styles = StyleSheet.create({
    container: {
        width: '100%',
    },
    tick: {
        position: 'absolute',
        fontFamily: fonts.mono,
        fontSize: TICK_FONT_SIZE,
        lineHeight: TICK_LINE_HEIGHT,
        color: colors.tertiary,
    },
    xTick: {
        textAlign: 'center',
    },
})
