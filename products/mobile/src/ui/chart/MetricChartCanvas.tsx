import { type ReactElement, useCallback, useMemo, useRef, useState } from 'react'
import { type LayoutChangeEvent, Text, View } from 'react-native'
import type { PointsArray } from 'victory-native'

import { createStyles, useTheme } from '@/ui/theme'
import { fonts } from '@/ui/tokens'

import { useChartAccessibility } from './accessibility/useChartAccessibility'
import { ChartOverlay } from './ChartOverlay'
import { chartGeometry, TICK_LINE_HEIGHT, X_LABEL_OFFSET, yPosition } from './chartGeometry'
import { samePoints, TICK_FONT_SIZE } from './chartMath'
import {
    bucketCount,
    bucketDates,
    chartSeriesOf,
    isCompareSeries,
    selectableMask,
    seriesStroke,
    visibleSeries,
} from './chartSeries'
import { useChartGestures } from './gestures/useChartGestures'
import { MetricChartRenderer, type PlottedSeries } from './MetricChartRenderer'
import { useChartSelection } from './selection/useChartSelection'
import type { ChartPoint, ChartSeries, MetricChartProps } from './types'
import { chartHeight } from './variant'

const NO_HIDDEN: readonly string[] = []

function sameSeries(a: readonly ChartSeries[], b: readonly ChartSeries[]): boolean {
    return (
        a.length === b.length &&
        a.every((s, index) => {
            const other = b[index]
            return (
                other !== undefined &&
                s.key === other.key &&
                s.label === other.label &&
                s.color === other.color &&
                s.style === other.style &&
                s.compareOf === other.compareOf &&
                s.incompleteFrom === other.incompleteFrom &&
                samePoints(s.points, other.points)
            )
        })
    )
}

/** Keeps the previous series when a parent passes equal ones, so re-renders do not clear the selection. */
function useStableSeries(series: ChartSeries[]): ChartSeries[] {
    const stable = useRef(series)
    if (!sameSeries(stable.current, series)) {
        stable.current = series
    }
    return stable.current
}

export function MetricChartCanvas(props: MetricChartProps): ReactElement {
    const {
        kind,
        interval,
        label,
        formatValue,
        variant = 'inline',
        hiddenKeys = NO_HIDDEN,
        dataUntil,
        onSelect,
        onPressTooltip,
        selectionId,
        trackingContext,
        accessibilitySummary,
        accessibilityActions,
        testID,
    } = props
    const theme = useTheme()
    const styles = useStyles()
    const height = chartHeight(variant, props.height)
    const series = useStableSeries(chartSeriesOf(props, theme))
    const accent = props.accent ? theme.accentColor[props.accent] : (series[0]?.color ?? theme.colors.blue)
    const [width, setWidth] = useState(0)
    const viewRef = useRef<View>(null)

    const visible = useMemo(() => visibleSeries(series, hiddenKeys), [series, hiddenKeys])
    const count = bucketCount(series)
    const dates = useMemo(() => bucketDates(series), [series])
    const mask = useMemo(() => selectableMask(visible, count), [visible, count])

    const geometry = useMemo(() => {
        const values = visible.flatMap((s) =>
            kind === 'bar' && isCompareSeries(s) ? [] : s.points.map((p) => p.value)
        )
        return chartGeometry({ width, height, kind, variant, count, values, dates, interval, formatValue })
    }, [width, height, kind, variant, count, visible, dates, interval, formatValue])

    const plotted = useMemo<PlottedSeries[]>(
        () =>
            visible.map((s) => {
                const ys = s.points.map((point) =>
                    Number.isFinite(point.value) ? yPosition(point.value, geometry.yDomain, geometry.plot) : Number.NaN
                )
                const points: PointsArray = s.points.map((point, index) => ({
                    x: geometry.xs[index] ?? 0,
                    xValue: index,
                    y: Number.isFinite(ys[index]) ? (ys[index] as number) : null,
                    yValue: Number.isFinite(point.value) ? point.value : null,
                }))
                const stroke = seriesStroke(s, theme)
                return {
                    key: s.key,
                    color: stroke.color,
                    dotted: stroke.dotted,
                    compare: isCompareSeries(s),
                    points,
                    ys,
                    incompleteFrom: s.incompleteFrom,
                }
            }),
        [visible, geometry, theme]
    )

    const pointAt = useCallback(
        (index: number): ChartPoint | null => {
            const primary = visible.find((s) => !isCompareSeries(s))
            const point = primary?.points[index]
            return point && Number.isFinite(point.value) ? point : null
        },
        [visible]
    )

    const selection = useChartSelection({
        selectionId,
        viewRef,
        dataKey: series,
        pointAt,
        onSelect,
        trackingContext,
        kind,
        seriesCount: visible.filter((s) => !isCompareSeries(s)).length,
    })
    const gestures = useChartGestures({
        variant,
        xs: geometry.xs,
        mask,
        values: selection.values,
        events: selection.events,
        listMovedAt: selection.listMovedAt,
    })
    const a11y = useChartAccessibility({
        label,
        kind,
        summary: accessibilitySummary,
        series,
        hiddenKeys,
        interval,
        formatValue,
        dataUntil,
        mask,
        selection,
        onPressTooltip,
        actions: accessibilityActions,
    })

    const onLayout = useCallback((event: LayoutChangeEvent): void => {
        setWidth(Math.round(event.nativeEvent.layout.width))
    }, [])

    return (
        <View
            ref={viewRef}
            style={[styles.container, { height }]}
            onLayout={onLayout}
            onTouchStart={selection.onTouchStart}
            testID={testID}
            {...a11y}
        >
            {width > 0 ? (
                <>
                    <MetricChartRenderer
                        geometry={geometry}
                        kind={kind}
                        variant={variant}
                        series={plotted}
                        accent={accent}
                        selection={selection.values}
                        gestures={gestures}
                    />
                    {geometry.yTicks.map(({ value, y, text }) =>
                        text === null ? null : (
                            <Text
                                key={`y-${value}`}
                                numberOfLines={1}
                                style={[
                                    styles.tick,
                                    { right: width - geometry.yLabelWidth, top: y - TICK_LINE_HEIGHT / 2 },
                                ]}
                            >
                                {text}
                            </Text>
                        )
                    )}
                    {geometry.xLabels.map(({ index, left, width: labelWidth, text }) => (
                        <Text
                            key={`x-${index}`}
                            numberOfLines={1}
                            style={[
                                styles.tick,
                                styles.xTick,
                                { left, width: labelWidth, top: geometry.plot.bottom + X_LABEL_OFFSET },
                            ]}
                        >
                            {text}
                        </Text>
                    ))}
                    <ChartOverlay
                        selection={selection.values}
                        geometry={geometry}
                        series={series}
                        hiddenKeys={hiddenKeys}
                        interval={interval}
                        variant={variant}
                        formatValue={formatValue}
                        dataUntil={dataUntil}
                        onPressTooltip={onPressTooltip}
                    />
                </>
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
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
}))
