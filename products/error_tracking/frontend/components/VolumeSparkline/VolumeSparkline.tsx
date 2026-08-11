import { useActions } from 'kea'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
    type ChartMargins,
    type DateRangeZoomData,
    type PointClickData,
    type Series,
    TimeSeriesBarChart,
    type TimeSeriesBarChartConfig,
    useChartHover,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { resolveVariableColor } from 'lib/charts/utils/color'
import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'

import { errorTrackingVolumeSparklineLogic } from './errorTrackingVolumeSparklineLogic'
import { EVENT_LABEL_BAR_GAP, EVENT_LABEL_HEIGHT, EventMarkers } from './EventMarkers'
import type {
    SparklineData,
    SparklineDatum,
    SparklineEvent,
    VolumeSparklineLayout,
    VolumeSparklineXAxisMode,
} from './types'

export type { VolumeSparklineLayout, VolumeSparklineXAxisMode } from './types'

/** Neutral bar color — volume is the subject here, so the bars stay grey and spikes carry the only
 *  color. Hover shading is quill's. */
const BAR_COLOR = 'var(--color-zinc-400)'

const SERIES_KEY = 'volume'

const LAYOUTS = {
    compact: { minBarSize: 2, barCornerRadius: 3, bandPadding: 0.22, padding: 'p-1' },
    detailed: { minBarSize: 10, barCornerRadius: 4, bandPadding: 0.1, padding: 'p-0' },
} as const satisfies Record<VolumeSparklineLayout, unknown>

const COMPACT_MARGINS = { left: 0, right: 0, top: 2, bottom: 2 }

/** Half of a "Jan 04"-ish axis label, so the first and last one aren't clipped at the plot edge. */
const EDGE_LABEL_RESERVE = 24

const TWO_DAYS_MS = 2 * 24 * 60 * 60 * 1000
const ONE_YEAR_MS = 365 * 24 * 60 * 60 * 1000

export type VolumeSparklineProps = {
    data: SparklineData
    layout: VolumeSparklineLayout
    sparklineKey: string
    xAxis?: VolumeSparklineXAxisMode
    className?: string
    events?: SparklineEvent<string>[]
    onRangeSelect?: (startDate: Date, endDate: Date) => void
    onSpikeClick?: (datum: SparklineDatum, clientX: number, clientY: number) => void
}

export function VolumeSparkline({
    sparklineKey,
    data,
    layout,
    xAxis = 'none',
    className,
    events = [],
    onRangeSelect,
    onSpikeClick,
}: VolumeSparklineProps): JSX.Element {
    const theme = useChartTheme()
    const { setHoveredBin, setHoveredEvent } = useActions(errorTrackingVolumeSparklineLogic({ sparklineKey }))
    // Quill reports a click's position relative to its own wrapper; the spike popover anchors in
    // viewport coordinates, so track the pointer here rather than converting after the fact.
    const cursorRef = useRef({ x: 0, y: 0 })
    const [eventHovered, setEventHovered] = useState(false)

    const dates = useMemo(() => data.map((datum) => datum.date), [data])
    const labels = useMemo(() => dates.map((date) => date.toISOString()), [dates])

    const series = useMemo<Series[]>(
        () => [
            {
                key: SERIES_KEY,
                label: 'Occurrences',
                // Bars are painted on a canvas, which can't resolve `var(--…)` — the colors have to be
                // concrete before they reach quill. Safe to resolve once (the resolver caches): the
                // palette and brand variables these use hold the same value in light and dark.
                color: resolveVariableColor(BAR_COLOR),
                data: data.map((datum) => datum.value),
                // A detected spike keeps its own color and picks up the hatch fill, so it reads as
                // flagged rather than just tall.
                bars: data.map((datum) =>
                    datum.animated && datum.color ? { color: resolveVariableColor(datum.color), hatch: true } : {}
                ),
            },
        ],
        [data]
    )

    const showAxis = xAxis !== 'none'
    const eventLabelReserve = events.length > 0 ? EVENT_LABEL_HEIGHT + EVENT_LABEL_BAR_GAP : undefined
    const tickFormatter = useMemo(() => buildTickFormatter(dates), [dates])

    const config = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            minBarSize: LAYOUTS[layout].minBarSize,
            barCornerRadius: LAYOUTS[layout].barCornerRadius,
            bandPadding: LAYOUTS[layout].bandPadding,
            margins: resolveMargins(layout, xAxis, eventLabelReserve),
            xAxis: { hide: xAxis !== 'full', tickFormatter },
            yAxis: { hide: true },
            showAxisLines: { x: showAxis, y: false },
            showTickMarks: false,
            showCrosshair: showAxis,
            showGrid: false,
            // Hover is surfaced as issue metrics beside the chart, not as a tooltip over it.
            tooltip: { enabled: false },
        }),
        [layout, xAxis, showAxis, eventLabelReserve, tickFormatter]
    )

    const onDateRangeZoom = useMemo(
        () =>
            onRangeSelect && data.length >= 2
                ? ({ startIndex, endIndex }: DateRangeZoomData) => {
                      const [from, to] = startIndex <= endIndex ? [startIndex, endIndex] : [endIndex, startIndex]
                      const start = data[from]?.date
                      const end = data[to]?.date
                      if (!start || !end) {
                          return
                      }
                      // The selection covers whole buckets, so the range runs to the end of the last one.
                      const bucketMs = data[1].date.getTime() - data[0].date.getTime()
                      onRangeSelect(start, new Date(end.getTime() + bucketMs))
                  }
                : undefined,
        [data, onRangeSelect]
    )

    // Wired only when a spike is actually present: quill shows the pointer cursor across the whole
    // chart whenever `onPointClick` is set, which would mask the drag-select crosshair.
    const hasSpikes = useMemo(() => data.some((datum) => datum.animated), [data])

    const onPointClick = useMemo(
        () =>
            onSpikeClick && hasSpikes
                ? ({ dataIndex }: PointClickData) => {
                      const datum = data[dataIndex]
                      if (datum?.animated) {
                          onSpikeClick(datum, cursorRef.current.x, cursorRef.current.y)
                      }
                  }
                : undefined,
        [data, hasSpikes, onSpikeClick]
    )

    const onEventHover = useCallback(
        (event: SparklineEvent<string> | null) => {
            setEventHovered(!!event)
            setHoveredEvent(event)
        },
        [setHoveredEvent]
    )

    return (
        <div
            className={cn('h-full w-full min-h-0 min-w-0 flex flex-col', LAYOUTS[layout].padding, className)}
            onMouseMove={(e) => {
                cursorRef.current = { x: e.clientX, y: e.clientY }
            }}
        >
            <TimeSeriesBarChart
                series={series}
                labels={labels}
                theme={theme}
                config={config}
                onDateRangeZoom={onDateRangeZoom}
                onPointClick={onPointClick}
                dataAttr="error-tracking-volume-sparkline"
            >
                <HoverReporter data={data} paused={eventHovered} onHoverBin={setHoveredBin} />
                {events.length > 0 && <EventMarkers events={events} dates={dates} onHover={onEventHover} />}
            </TimeSeriesBarChart>
        </div>
    )
}

/** Publishes the hovered bucket to the sparkline's logic, so the surrounding scene can swap its
 *  metrics for that bucket's values. A chart child because `useChartHover` is only available inside
 *  the chart; `paused` yields to an event marker's own hover, which owns the same logic field. */
function HoverReporter({
    data,
    paused,
    onHoverBin,
}: {
    data: SparklineData
    paused: boolean
    onHoverBin: (payload: { index: number; datum: SparklineDatum } | null) => void
}): null {
    const { hoverIndex } = useChartHover()
    const index = paused ? -1 : hoverIndex

    useEffect(() => {
        const datum = data[index]
        onHoverBin(index >= 0 && datum ? { index, datum } : null)
    }, [index, data, onHoverBin])

    return null
}

/** Plot insets. Compact runs the bars edge to edge; detailed reserves room above for the event pills,
 *  and room either side for the first and last axis labels — those are centered on their bucket, and
 *  the chart clips anything outside the plot. */
function resolveMargins(
    layout: VolumeSparklineLayout,
    xAxis: VolumeSparklineXAxisMode,
    eventLabelReserve: number | undefined
): Partial<ChartMargins> | undefined {
    if (layout === 'compact') {
        return COMPACT_MARGINS
    }
    const horizontal = xAxis === 'full' ? EDGE_LABEL_RESERVE : undefined
    if (eventLabelReserve == null && horizontal == null) {
        return undefined
    }
    return { top: eventLabelReserve, left: horizontal, right: horizontal }
}

/** Axis ticks in the browser's timezone, at the coarsest granularity the range allows, keeping only
 *  the first bucket of each distinct label so a multi-bucket day is labelled once (quill then thins
 *  whatever still overlaps). */
function buildTickFormatter(dates: Date[]): (value: string, index: number) => string | null {
    const spanMs = dates.length > 1 ? dates[dates.length - 1].getTime() - dates[0].getTime() : 0
    const format = spanMs <= TWO_DAYS_MS ? 'HH:mm' : spanMs <= ONE_YEAR_MS ? 'MMM DD' : 'MMM YYYY'

    const seen = new Set<string>()
    const ticks = dates.map((date) => {
        const text = dayjs(date).format(format)
        if (seen.has(text)) {
            return null
        }
        seen.add(text)
        return text
    })

    return (_value, index) => ticks[index] ?? null
}
