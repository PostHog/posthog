import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import {
    type ChartMargins,
    createXAxisTickCallback,
    type DateRangeZoomData,
    type PointClickData,
    type Series,
    TimeSeriesBarChart,
    type TimeSeriesBarChartConfig,
    useChartHover,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { resolveVariableColor } from 'lib/charts/utils/color'
import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'

import { errorTrackingVolumeSparklineLogic } from './errorTrackingVolumeSparklineLogic'
import { EVENT_LABEL_BAR_GAP, EVENT_LABEL_HEIGHT, EventMarkers } from './EventMarkers'
import { SpikeStripes } from './SpikeStripes'
import type {
    SparklineData,
    SparklineDatum,
    SparklineEvent,
    VolumeSparklineLayout,
    VolumeSparklineXAxisMode,
} from './types'

export type { VolumeSparklineLayout, VolumeSparklineXAxisMode } from './types'

/** zinc-400. Hex, not the token: its value is `oklch()`, which d3-color can't parse, so quill's
 *  hover shade falls back to the bar's own color and the highlight disappears. */
const BAR_COLOR = '#9f9fa9'

const SERIES_KEY = 'volume'

type LayoutPreset = {
    minBarSize: number
    barCornerRadius: number
    bandPadding: number
    padding: string
}

const LAYOUTS = {
    compact: { minBarSize: 2, barCornerRadius: 3, bandPadding: 0.22, padding: 'p-1' },
    detailed: { minBarSize: 10, barCornerRadius: 4, bandPadding: 0.1, padding: 'p-0' },
} as const satisfies Record<VolumeSparklineLayout, LayoutPreset>

const COMPACT_MARGINS = { left: 0, right: 0, top: 2, bottom: 2 }

export type VolumeSparklineProps = {
    data: SparklineData
    layout: VolumeSparklineLayout
    sparklineKey: string
    xAxis?: VolumeSparklineXAxisMode
    className?: string
    events?: SparklineEvent<string>[]
    onRangeSelect?: (startDate: Date, endDate: Date) => void
    onBucketClick?: (startDate: Date, endDate: Date) => void
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
    onBucketClick,
    onSpikeClick,
}: VolumeSparklineProps): JSX.Element {
    const theme = useChartTheme()
    const { timezone } = useValues(teamLogic)
    const { setHoveredEvent } = useActions(errorTrackingVolumeSparklineLogic({ sparklineKey }))
    // Quill reports clicks relative to its wrapper; the spike popover anchors in viewport coords.
    const cursorRef = useRef({ x: 0, y: 0 })

    const dates = useMemo(() => data.map((datum) => datum.date), [data])
    const labels = useMemo(() => dates.map((date) => date.toISOString()), [dates])
    // The y-axis is hidden, so quill's default `d3.nice()` rounding would only add invisible
    // headroom that shortens every bar — pin the domain so the tallest bar reaches the plot top.
    const maxValue = useMemo(() => Math.max(1, ...data.map((datum) => datum.value)), [data])

    const series = useMemo<Series[]>(
        () => [
            {
                key: SERIES_KEY,
                label: 'Occurrences',
                // Canvas can't resolve `var(--…)`; `BAR_COLOR` is already a hex literal.
                color: BAR_COLOR,
                data: data.map((datum) => datum.value),
                // Solid here, striped by `SpikeStripes`. quill's `hatch` is a de-emphasis
                // treatment, so it reads as unfinished rather than flagged.
                bars: data.map((datum) =>
                    datum.isSpike && datum.color ? { color: resolveVariableColor(datum.color) } : {}
                ),
            },
        ],
        [data]
    )

    const showAxis = xAxis !== 'none'
    const eventLabelReserve = events.length > 0 ? EVENT_LABEL_HEIGHT + EVENT_LABEL_BAR_GAP : undefined
    // Quill's own tick callback: project-timezone labels at the granularity it infers from the
    // bucket spacing, deduped per period. Only built when ticks actually render.
    const tickFormatter = useMemo(
        () => (xAxis === 'full' ? createXAxisTickCallback({ timezone, allDays: labels }) : undefined),
        [labels, timezone, xAxis]
    )

    const config = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            minBarSize: LAYOUTS[layout].minBarSize,
            barCornerRadius: LAYOUTS[layout].barCornerRadius,
            bandPadding: LAYOUTS[layout].bandPadding,
            margins: resolveMargins(layout, eventLabelReserve),
            valueDomain: { min: 0, max: maxValue },
            xAxis: { hide: xAxis !== 'full', tickFormatter },
            yAxis: { hide: true },
            showAxisLines: { x: showAxis, y: false },
            showTickMarks: false,
            showCrosshair: showAxis,
            showGrid: false,
            // Hover is surfaced as issue metrics beside the chart, not as a tooltip over it.
            tooltip: { enabled: false },
        }),
        [layout, xAxis, showAxis, eventLabelReserve, tickFormatter, maxValue]
    )

    const onDateRangeZoom = useMemo(() => {
        if (!onRangeSelect || data.length < 2) {
            return undefined
        }
        // Zero when the data is a placeholder filled with a single timestamp (see
        // `generateFallbackData`) — a drag would select an empty range.
        const bucketMs = data[1].date.getTime() - data[0].date.getTime()
        if (bucketMs <= 0) {
            return undefined
        }
        return ({ startIndex, endIndex }: DateRangeZoomData) => {
            const start = data[startIndex]?.date
            const end = data[endIndex]?.date
            if (!start || !end) {
                return
            }
            // The selection covers whole buckets, so the range runs to the end of the last one.
            onRangeSelect(start, new Date(end.getTime() + bucketMs))
        }
    }, [data, onRangeSelect])

    const hasSpikes = useMemo(() => data.some((datum) => datum.isSpike), [data])

    const onPointClick = useMemo(() => {
        if (!onBucketClick && !(onSpikeClick && hasSpikes)) {
            return undefined
        }
        return ({ dataIndex }: PointClickData) => {
            const datum = data[dataIndex]
            if (!datum) {
                return
            }
            const adjacentDate = data[dataIndex + 1]?.date
            const previousDate = data[dataIndex - 1]?.date
            const endDate =
                adjacentDate ??
                (previousDate ? new Date(datum.date.getTime() + datum.date.getTime() - previousDate.getTime()) : null)
            // A flagged spike takes precedence: it opens the spike details popover rather than
            // filtering to the bucket, so callers passing both handlers still reach the popover.
            if (datum.isSpike && onSpikeClick) {
                onSpikeClick(datum, cursorRef.current.x, cursorRef.current.y)
                return
            }
            if (onBucketClick && endDate && endDate.getTime() > datum.date.getTime()) {
                onBucketClick(datum.date, endDate)
            }
        }
    }, [data, hasSpikes, onBucketClick, onSpikeClick])

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
                <HoverReporter sparklineKey={sparklineKey} data={data} />
                {hasSpikes && (
                    <SpikeStripes
                        data={data}
                        minBarSize={LAYOUTS[layout].minBarSize}
                        cornerRadius={LAYOUTS[layout].barCornerRadius}
                    />
                )}
                {events.length > 0 && <EventMarkers events={events} dates={dates} onHover={setHoveredEvent} />}
            </TimeSeriesBarChart>
        </div>
    )
}

/** A chart child because `useChartHover` only works inside the chart. Yields to an event marker's
 *  hover (which writes the same logic field), reading it here rather than in the chart host so
 *  mousemove-driven re-renders stay contained to this null-rendering component. */
function HoverReporter({ sparklineKey, data }: { sparklineKey: string; data: SparklineData }): null {
    const { hoverIndex } = useChartHover()
    const { hoverSelection } = useValues(errorTrackingVolumeSparklineLogic({ sparklineKey }))
    const { setHoveredBin } = useActions(errorTrackingVolumeSparklineLogic({ sparklineKey }))
    const paused = hoverSelection?.kind === 'event'

    useEffect(() => {
        if (paused) {
            return
        }
        const datum = data[hoverIndex]
        setHoveredBin(hoverIndex >= 0 && datum ? { index: hoverIndex, datum } : null)
    }, [hoverIndex, paused, data, setHoveredBin])

    // Reset on unmount so a parent still mounted after the chart tears down doesn't keep showing
    // the last hovered bucket (mirrors quill's own `Sparkline.tsx` `HoverWatcher`).
    useEffect(() => () => setHoveredBin(null), [setHoveredBin])

    return null
}

/** Plot insets. The left and right edges are left to the chart's own computed margins, which
 *  reserve enough for the widest axis label at the real axis font; a flat override here would just
 *  reintroduce the clipping they prevent. */
function resolveMargins(layout: VolumeSparklineLayout, eventLabelReserve: number | undefined): Partial<ChartMargins> {
    if (layout === 'compact') {
        return COMPACT_MARGINS
    }
    return { top: eventLabelReserve }
}
