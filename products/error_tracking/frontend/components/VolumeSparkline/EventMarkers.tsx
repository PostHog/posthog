import { useLayoutEffect, useMemo, useRef, useState } from 'react'

import { useChartLayout } from '@posthog/quill-charts'

import { spreadLabels } from './spreadLabels'
import type { SparklineEvent } from './types'

/** Gap between the pill labels and the top of the bars. Paired with `EVENT_LABEL_HEIGHT` to size the
 *  chart's top margin, so the pills sit in reserved space rather than over the bars. */
export const EVENT_LABEL_BAR_GAP = 10
export const EVENT_LABEL_HEIGHT = 20
const EVENT_LABEL_MIN_GAP = 2
const ANCHOR_RADIUS = 6

export type EventMarkersProps = {
    events: SparklineEvent<string>[]
    /** Bucket start dates, one per chart label — the timeline the event timestamps are placed on. */
    dates: Date[]
    onHover: (event: SparklineEvent<string> | null) => void
}

/** Timeline annotations (first seen, last seen, the selected event) drawn over the volume chart: a
 *  pill label in the chart's top margin, a connector down to the x-axis, and an anchor dot on it.
 *
 *  A chart child rather than part of the chart: it reads pixel positions from `useChartLayout()` and
 *  renders DOM, so an event at an arbitrary timestamp can be placed between two buckets — quill's
 *  band scale only resolves whole labels. */
export function EventMarkers({ events, dates, onHover }: EventMarkersProps): JSX.Element | null {
    const { scales, dimensions, labels } = useChartLayout()
    const labelRefs = useRef<(HTMLDivElement | null)[]>([])
    const [halfWidths, setHalfWidths] = useState<number[] | null>(null)

    const { plotLeft, plotTop, plotWidth, plotHeight } = dimensions
    const plotRight = plotLeft + plotWidth
    const plotBottom = plotTop + plotHeight

    // Continuous time → x, so an event between two bucket starts lands between their bars. Bars are
    // band-scaled, so the step comes from two adjacent band centers and x is measured from the
    // first bucket's left edge (where its own timestamp sits).
    const positionAt = useMemo((): ((time: number) => number) | null => {
        if (dates.length < 2 || labels.length < 2) {
            return null
        }
        const firstCenter = scales.x(labels[0])
        const secondCenter = scales.x(labels[1])
        if (firstCenter == null || secondCenter == null || !isFinite(firstCenter) || !isFinite(secondCenter)) {
            return null
        }
        const step = secondCenter - firstCenter
        const bucketMs = dates[1].getTime() - dates[0].getTime()
        if (step === 0 || bucketMs === 0) {
            return null
        }
        const originX = firstCenter - step / 2
        const originTime = dates[0].getTime()
        return (time: number) => originX + ((time - originTime) / bucketMs) * step
    }, [dates, labels, scales])

    const anchors = useMemo(
        () => (positionAt ? events.map((event) => positionAt(event.date.getTime())) : []),
        [events, positionAt]
    )

    // Measure the rendered pills, then place them: the labels are author-supplied strings, so their
    // widths aren't known until the browser has laid them out. Runs before paint, so the unmeasured
    // first pass is never visible.
    const measureKey = `${events.map((e) => e.id + e.payload).join('|')}|${plotWidth}`
    useLayoutEffect(() => {
        const measured = labelRefs.current.slice(0, events.length).map((node) => (node?.offsetWidth ?? 0) / 2)
        setHalfWidths((previous) =>
            previous && previous.length === measured.length && previous.every((w, i) => w === measured[i])
                ? previous
                : measured
        )
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [measureKey, events.length])

    const labelCenters = useMemo(() => {
        if (!halfWidths || halfWidths.length !== anchors.length) {
            return null
        }
        const items = anchors.map((center, index) => ({ center, halfWidth: halfWidths[index] }))
        return spreadLabels(items, EVENT_LABEL_MIN_GAP, plotLeft, plotRight)
    }, [anchors, halfWidths, plotLeft, plotRight])

    if (!positionAt || events.length === 0) {
        return null
    }

    const labelTop = Math.max(0, plotTop - EVENT_LABEL_BAR_GAP - EVENT_LABEL_HEIGHT)

    return (
        <>
            <svg className="absolute inset-0 w-full h-full pointer-events-none overflow-visible">
                {events.map((event, index) => {
                    const anchorX = anchors[index]
                    // An event outside the chart's date range keeps its pill (clamped into view) but
                    // drops the connector — a line to an off-chart anchor would point at nothing.
                    if (anchorX < plotLeft || anchorX > plotRight) {
                        return null
                    }
                    const color = event.color || 'black'
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
                            <circle
                                cx={anchorX}
                                cy={plotBottom}
                                r={event.radius ?? ANCHOR_RADIUS}
                                fill="white"
                                stroke={color}
                                strokeWidth={2}
                            />
                        </g>
                    )
                })}
            </svg>
            {events.map((event, index) => (
                <div
                    key={event.id}
                    ref={(node) => {
                        labelRefs.current[index] = node
                    }}
                    data-attr="error-tracking-volume-event-label"
                    className="absolute flex items-center px-[5px] rounded text-[10px] font-semibold text-white whitespace-nowrap cursor-default"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        top: labelTop,
                        height: EVENT_LABEL_HEIGHT,
                        // Pre-measurement the pill is laid out at its anchor and hidden, so the
                        // browser reports its natural width without a visible unspread frame.
                        left: labelCenters ? labelCenters[index] - (halfWidths?.[index] ?? 0) : anchors[index],
                        visibility: labelCenters ? 'visible' : 'hidden',
                        backgroundColor: event.color || 'black',
                        pointerEvents: 'auto',
                    }}
                    onMouseEnter={() => onHover(event)}
                    onMouseLeave={() => onHover(null)}
                >
                    {event.payload}
                </div>
            ))}
        </>
    )
}
