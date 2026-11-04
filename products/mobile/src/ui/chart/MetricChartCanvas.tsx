import { useCalendars } from 'expo-localization'
import { type ReactElement, useCallback, useMemo, useRef, useState } from 'react'
import { type LayoutChangeEvent, Text, View } from 'react-native'
import type { PointsArray } from 'victory-native'

import { prefers24HourClock } from '@/lib/dates'
import { createStyles, useTheme } from '@/ui/theme'
import { fonts } from '@/ui/tokens'

import { useChartAccessibility } from './accessibility/useChartAccessibility'
import { barPageSize, barSegments, barWindow } from './barLayout'
import { ChartDatePager } from './ChartDatePager'
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
import type { ChartPoint, ChartSeries, ChartTooltipPoint, MetricChartProps } from './types'
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
        barLayout = 'grouped',
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
    const [calendar] = useCalendars()
    const uses24hourClock = prefers24HourClock(calendar.uses24hourClock)
    const theme = useTheme()
    const styles = useStyles()
    const fullHeight = chartHeight(variant, props.height)
    const allSeries = useStableSeries(chartSeriesOf(props, theme))
    const accent = props.accent ? theme.accentColor[props.accent] : (allSeries[0]?.color ?? theme.colors.blue)
    const [width, setWidth] = useState(0)
    const viewRef = useRef<View>(null)

    const [page, setPage] = useState({ data: allSeries, endOffset: 0 })
    const endOffset = page.data === allSeries ? page.endOffset : 0
    const allVisible = useMemo(() => visibleSeries(allSeries, hiddenKeys), [allSeries, hiddenKeys])
    const totalCount = bucketCount(allSeries)
    const currentCount = allVisible.filter((s) => !isCompareSeries(s)).length
    const allSegments = useMemo(() => barSegments(allVisible, barLayout), [allVisible, barLayout])
    const axisValues = useMemo(
        () =>
            allVisible.flatMap((s, index) =>
                kind === 'bar'
                    ? isCompareSeries(s)
                        ? []
                        : [...(allSegments[index]?.starts ?? []), ...(allSegments[index]?.ends ?? [])]
                    : s.points.map((p) => p.value)
            ),
        [allVisible, allSegments, kind]
    )
    const axisGeometry = useMemo(
        () =>
            chartGeometry({
                width,
                height: fullHeight,
                kind,
                variant,
                count: totalCount,
                values: axisValues,
                dates: [],
                uses24hourClock,
                interval,
                formatValue,
            }),
        [width, fullHeight, kind, variant, totalCount, axisValues, interval, formatValue, uses24hourClock]
    )
    const pageSize = barPageSize(axisGeometry.plot.right - axisGeometry.plot.left, currentCount, barLayout)
    const paged = kind === 'bar' && variant !== 'compact' && width > 0 && totalCount > pageSize
    const window = barWindow(totalCount, paged ? pageSize : Math.max(1, totalCount), endOffset)
    const series = useMemo(
        () =>
            paged
                ? allSeries.map((s) => ({
                      ...s,
                      points: s.points.slice(window.start, window.end),
                      incompleteFrom:
                          s.incompleteFrom === undefined ? undefined : Math.max(0, s.incompleteFrom - window.start),
                  }))
                : allSeries,
        [allSeries, paged, window.start, window.end]
    )
    const height = paged ? fullHeight - 44 : fullHeight
    const visible = useMemo(() => visibleSeries(series, hiddenKeys), [series, hiddenKeys])
    const count = bucketCount(series)
    const dates = useMemo(() => bucketDates(series), [series])
    const mask = useMemo(() => selectableMask(visible, count), [visible, count])
    const segments = useMemo(() => barSegments(visible, barLayout), [visible, barLayout])

    const geometry = useMemo(() => {
        return chartGeometry({
            width,
            height,
            kind,
            variant,
            count,
            values: axisValues,
            dates,
            interval,
            formatValue,
            uses24hourClock,
        })
    }, [width, height, kind, variant, count, axisValues, dates, interval, formatValue, uses24hourClock])

    const plotted = useMemo<PlottedSeries[]>(
        () =>
            visible.map((s, seriesIndex) => {
                const segment = segments[seriesIndex]
                const ys = s.points.map((point, index) =>
                    Number.isFinite(point.value)
                        ? yPosition(
                              kind === 'bar' ? (segment?.ends[index] ?? 0) : point.value,
                              geometry.yDomain,
                              geometry.plot
                          )
                        : Number.NaN
                )
                const baseYs = s.points.map((_, index) =>
                    yPosition(segment?.starts[index] ?? 0, geometry.yDomain, geometry.plot)
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
                    baseYs,
                    incompleteFrom: s.incompleteFrom,
                }
            }),
        [visible, geometry, segments, kind, theme]
    )

    const pressTooltip = useMemo(
        () =>
            onPressTooltip
                ? (point: ChartTooltipPoint): void => {
                      onPressTooltip({ ...point, index: point.index + (paged ? window.start : 0) })
                  }
                : undefined,
        [onPressTooltip, paged, window.start]
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
        onPressTooltip: pressTooltip,
        actions: accessibilityActions,
    })

    const onLayout = useCallback((event: LayoutChangeEvent): void => {
        setWidth(Math.round(event.nativeEvent.layout.width))
    }, [])

    return (
        <View onLayout={onLayout}>
            {paged ? (
                <ChartDatePager
                    from={dates[0] ?? 0}
                    to={dates[dates.length - 1] ?? 0}
                    interval={interval}
                    earlier={window.start > 0}
                    later={window.end < totalCount}
                    onEarlier={() => setPage({ data: allSeries, endOffset: totalCount - window.start })}
                    onLater={() =>
                        setPage({ data: allSeries, endOffset: Math.max(0, totalCount - window.end - pageSize) })
                    }
                />
            ) : null}
            <View
                ref={viewRef}
                style={[styles.container, { height }]}
                onTouchStart={selection.onTouchStart}
                testID={testID}
                {...a11y}
            >
                {width > 0 ? (
                    <>
                        <MetricChartRenderer
                            key={`${geometry.width}:${geometry.height}`}
                            geometry={geometry}
                            kind={kind}
                            barLayout={barLayout}
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
                            onPressTooltip={pressTooltip}
                        />
                    </>
                ) : null}
            </View>
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
