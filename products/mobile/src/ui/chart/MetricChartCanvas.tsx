import { type ReactElement, useCallback, useMemo, useRef, useState } from 'react'
import { type LayoutChangeEvent, StyleSheet, Text, View } from 'react-native'
import type { Scale } from 'victory-native'

import { accentColor, colors, fonts, lineHeight } from '@/ui/tokens'

import { ChartTooltip } from './ChartTooltip'
import {
    CHART_DEFAULT_HEIGHT,
    formatAxisDate,
    formatTooltipDate,
    monoTextWidth,
    samePoints,
    TICK_FONT_SIZE,
    TICK_GAP,
    tooltipLeft,
    xTickIndices,
    yAxisTicks,
} from './chartMath'
import { useChartGestures } from './gestures/useChartGestures'
import { type Datum, MetricChartRenderer } from './MetricChartRenderer'
import { useChartSelection } from './selection/useChartSelection'
import type { ChartPoint, MetricChartProps } from './types'

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
    const [tooltipWidth, setTooltipWidth] = useState(0)

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

    const selection = useChartSelection(points, values, onSelect)
    const gestures = useChartGestures(xs, selection.selectByTap)

    const onLayout = useCallback((event: LayoutChangeEvent): void => {
        setWidth(Math.round(event.nativeEvent.layout.width))
    }, [])
    const onScaleChange = useCallback((x: Scale, y: Scale): void => setScales({ x, y }), [])

    const selectedPoint = points[selection.selectedIndex]
    const anchorX = xs[selection.selectedIndex]
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
                <MetricChartRenderer
                    data={data}
                    kind={kind}
                    color={color}
                    width={width}
                    height={height}
                    padding={padding}
                    domain={domain}
                    gridlines={gridlines}
                    pressState={selection.pressState}
                    gestures={gestures}
                    selected={selection.selected}
                    xs={xs}
                    ys={ys}
                    onScaleChange={onScaleChange}
                />
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
