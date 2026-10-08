import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { useChartLayout } from '@posthog/quill-charts'

import { buildTimePositioner } from './buildTimePositioner'
import { spreadLabels } from './spreadLabels'
import type { SparklineEvent } from './types'

/** With `EVENT_LABEL_HEIGHT`, sizes the chart's top margin so pills sit above the bars. */
export const EVENT_LABEL_BAR_GAP = 10
export const EVENT_LABEL_HEIGHT = 20
const EVENT_LABEL_MIN_GAP = 2
const DEFAULT_EVENT_COLOR = 'black'

export type EventMarkersProps = {
    events: SparklineEvent<string>[]
    /** Bucket start dates, one per chart label — the timeline the event timestamps are placed on. */
    dates: Date[]
    onHover: (event: SparklineEvent<string> | null) => void
}

/** DOM positioned off `useChartLayout()`, so an event can sit between two buckets — quill's band
 *  scale only resolves whole labels. Memoized: it renders inside the chart host, whose props are
 *  stable across the hover-driven re-renders `useChartLayout` deliberately doesn't cause. */
export const EventMarkers = memo(function EventMarkers({
    events,
    dates,
    onHover,
}: EventMarkersProps): JSX.Element | null {
    const { scales, dimensions, labels } = useChartLayout()
    const labelRefs = useRef<(HTMLDivElement | null)[]>([])
    const [halfWidths, setHalfWidths] = useState<number[] | null>(null)

    const { plotLeft, plotTop, plotWidth, plotHeight } = dimensions
    const plotRight = plotLeft + plotWidth
    const plotBottom = plotTop + plotHeight

    const positionAt = useMemo(() => buildTimePositioner(dates, labels, scales.x), [dates, labels, scales])

    // React fires no `onMouseLeave` when it unmounts a hovered pill, which would strand its hover
    // in the state the bar hover shares.
    const hoveredId = useRef<string | null>(null)
    const handleHover = useCallback(
        (event: SparklineEvent<string> | null) => {
            hoveredId.current = event?.id ?? null
            onHover(event)
        },
        [onHover]
    )
    const clearStrandedHover = useCallback(() => {
        if (hoveredId.current != null) {
            hoveredId.current = null
            onHover(null)
        }
    }, [onHover])

    // An event outside the charted range has no bar to point at, so it gets no pill either. A
    // clamped pill at the plot edge reads as if the event happened at that bucket. The range is
    // compared in time, not pixels, so the check does not depend on the band scale's outer padding.
    const placed = useMemo(() => {
        if (!positionAt) {
            return []
        }
        const start = dates[0].getTime()
        const end = dates[dates.length - 1].getTime() + (dates[1].getTime() - dates[0].getTime())
        return events.flatMap((event) => {
            const time = event.date.getTime()
            return time >= start && time <= end ? [{ event, anchor: positionAt(time) }] : []
        })
    }, [events, dates, positionAt])
    const visibleEvents = useMemo(() => placed.map((item) => item.event), [placed])
    const anchors = useMemo(() => placed.map((item) => item.anchor), [placed])

    useEffect(() => {
        if (hoveredId.current != null && !visibleEvents.some((event) => event.id === hoveredId.current)) {
            clearStrandedHover()
        }
    }, [visibleEvents, clearStrandedHover])

    useEffect(() => clearStrandedHover, [clearStrandedHover])

    // Pill widths aren't known until laid out.
    const measurePills = useCallback(() => {
        const measured = labelRefs.current.slice(0, visibleEvents.length).map((node) => (node?.offsetWidth ?? 0) / 2)
        setHalfWidths((previous) =>
            previous && previous.length === measured.length && previous.every((w, i) => w === measured[i])
                ? previous
                : measured
        )
    }, [visibleEvents.length])

    const pillTexts = useMemo(() => visibleEvents.map((event) => event.payload).join('\u0000'), [visibleEvents])
    useLayoutEffect(() => {
        measurePills()
    }, [measurePills, pillTexts, plotWidth])

    // A webfont arriving after first paint changes pill widths without any prop changing.
    useEffect(() => {
        let cancelled = false
        document.fonts?.ready.then(() => {
            if (!cancelled) {
                measurePills()
            }
        })
        return () => {
            cancelled = true
        }
    }, [measurePills])

    const labelCenters = useMemo(() => {
        if (!halfWidths || halfWidths.length !== anchors.length) {
            return null
        }
        const items = anchors.map((center, index) => ({ center, halfWidth: halfWidths[index] }))
        return spreadLabels(items, EVENT_LABEL_MIN_GAP, plotLeft, plotRight)
    }, [anchors, halfWidths, plotLeft, plotRight])

    if (visibleEvents.length === 0) {
        return null
    }

    const labelTop = Math.max(0, plotTop - EVENT_LABEL_BAR_GAP - EVENT_LABEL_HEIGHT)

    return (
        <>
            <svg className="absolute inset-0 w-full h-full pointer-events-none overflow-visible">
                {visibleEvents.map((event, index) => {
                    const anchorX = anchors[index]
                    const color = event.color || DEFAULT_EVENT_COLOR
                    return (
                        <g key={event.id}>
                            <line
                                x1={anchorX}
                                y1={plotBottom}
                                x2={labelCenters?.[index] ?? anchorX}
                                y2={labelTop + EVENT_LABEL_HEIGHT}
                                stroke={color}
                                strokeWidth={2}
                            />
                            {/* The dot is a knockout against the chart surface, not literally white. */}
                            <circle cx={anchorX} cy={plotBottom} r={3} fill={color} />
                        </g>
                    )
                })}
            </svg>
            {visibleEvents.map((event, index) => (
                <div
                    key={event.id}
                    ref={(node) => {
                        labelRefs.current[index] = node
                    }}
                    data-attr="error-tracking-volume-event-label"
                    className="absolute flex items-center px-2 rounded text-[10px] font-semibold text-white whitespace-nowrap cursor-default"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        top: labelTop,
                        height: EVENT_LABEL_HEIGHT,
                        // Hidden at its anchor until measured, so no unspread frame is visible.
                        left: labelCenters ? labelCenters[index] - (halfWidths?.[index] ?? 0) : anchors[index],
                        visibility: labelCenters ? 'visible' : 'hidden',
                        backgroundColor: event.color || DEFAULT_EVENT_COLOR,
                        pointerEvents: 'auto',
                    }}
                    onMouseEnter={() => handleHover(event)}
                    onMouseLeave={() => handleHover(null)}
                >
                    {event.payload}
                </div>
            ))}
        </>
    )
})
