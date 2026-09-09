/* eslint-disable react/forbid-dom-props -- dynamic pixel positions from the chart scales */
import { useLayoutEffect, useRef, useState } from 'react'

import { useChartLayout } from '@posthog/quill-charts'

import type { SpendMarker, SpendMarkerTone } from './spendTrajectoryTransforms'

const LABEL_CLEARANCE = 12
const LABEL_ABOVE = 6
const LABEL_BELOW = 10
const LABEL_LINE_GAP = 3
const LABEL_INSET = 4
const LABEL_GAP = 9
const COLLISION_PADDING = 2
const MIN_LEFT_TEXT_ROOM = 60
const CROSSING_TEXT_WIDTH = 90

const TONE_CLASS: Record<SpendMarkerTone, string> = {
    default: 'text-primary',
    muted: 'text-muted',
    danger: 'text-danger',
}

type CaptionSide = 'start' | 'end'

export interface SpendReferenceLabel {
    key: 'limit' | 'free'
    value: number
    text: string
    tone: SpendMarkerTone
    position: CaptionSide
}

interface SpendTrajectoryMarkersProps {
    markers: SpendMarker[]
    /** Drawn here instead of through the library label, whose background bubble would hide the line. */
    referenceLabels: SpendReferenceLabel[]
}

interface Box {
    left: number
    right: number
    top: number
    bottom: number
}

function toBox(rect: DOMRect, origin: DOMRect): Box {
    return {
        left: rect.left - origin.left - COLLISION_PADDING,
        right: rect.right - origin.left + COLLISION_PADDING,
        top: rect.top - origin.top - COLLISION_PADDING,
        bottom: rect.bottom - origin.top + COLLISION_PADDING,
    }
}

function overlaps(a: Box, b: Box): boolean {
    return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom
}

export function SpendTrajectoryMarkers({ markers, referenceLabels }: SpendTrajectoryMarkersProps): JSX.Element {
    const { scales, dimensions, series } = useChartLayout()
    const rootRef = useRef<HTMLDivElement>(null)
    const [captionLefts, setCaptionLefts] = useState<Partial<Record<SpendReferenceLabel['key'], number>>>({})
    const plotRight = dimensions.plotLeft + dimensions.plotWidth
    // Lowest line first, so a label pushed past one is then tested against the next one up.
    const referenceYs = referenceLabels.map((line) => scales.y(line.value)).sort((a, b) => b - a)

    // Labels sit above their anchor. Below a point is the filled area and the rising curve, so a label
    // blocked by a reference line climbs past it instead of dropping into the fill.
    const labelTop = (anchorY: number): number => {
        let candidate = anchorY - LABEL_ABOVE
        for (const reference of referenceYs) {
            if (Math.abs(candidate - reference) < LABEL_CLEARANCE) {
                candidate = reference - LABEL_CLEARANCE
            }
        }
        return candidate < dimensions.plotTop ? anchorY + LABEL_BELOW : candidate
    }

    // Text widths are only known once rendered, so captions are measured after layout and a covered one
    // moves along its line. Candidates come from the measured width, so this settles in one extra render.
    useLayoutEffect(() => {
        const root = rootRef.current
        const origin = root?.parentElement?.getBoundingClientRect()
        if (!root || !origin) {
            return
        }
        const markerBoxes = Array.from(
            root.querySelectorAll<HTMLElement>('[data-attr^="spend-trajectory-marker-"] > span:last-child')
        ).map((el) => toBox(el.getBoundingClientRect(), origin))
        const lineStart = dimensions.plotLeft + LABEL_INSET
        const lineEnd = plotRight - LABEL_INSET
        const next: Partial<Record<SpendReferenceLabel['key'], number>> = {}
        for (const line of referenceLabels) {
            const el = root.querySelector<HTMLElement>(`[data-attr="spend-trajectory-reference-label-${line.key}"]`)
            if (!el) {
                continue
            }
            const measured = el.getBoundingClientRect()
            const width = measured.width
            const strip = toBox(measured, origin)
            const boxAt = (left: number): Box => ({
                ...strip,
                left: left - COLLISION_PADDING,
                right: left + width + COLLISION_PADDING,
            })
            const isFree = (left: number): boolean => !markerBoxes.some((marker) => overlaps(marker, boxAt(left)))
            const atStart = lineStart
            const atEnd = lineEnd - width
            const candidates = line.position === 'end' ? [atEnd, atStart] : [atStart, atEnd]
            const blockers = markerBoxes
                .filter((marker) => overlaps(marker, { ...strip, left: lineStart, right: lineEnd }))
                .sort((a, b) => a.left - b.left)
            const gaps: [number, number][] = []
            let cursor = lineStart
            for (const blocker of blockers) {
                gaps.push([cursor, blocker.left])
                cursor = Math.max(cursor, blocker.right)
            }
            gaps.push([cursor, lineEnd])
            for (const [from, to] of gaps.sort((a, b) => b[1] - b[0] - (a[1] - a[0]))) {
                if (to - from >= width) {
                    candidates.push(from + (to - from - width) / 2)
                }
            }
            next[line.key] = candidates.find(isFree) ?? candidates[0]
        }
        setCaptionLefts((prev) => (referenceLabels.some((line) => next[line.key] !== prev[line.key]) ? next : prev))
    }, [markers, referenceLabels, scales, dimensions, plotRight])

    return (
        <div ref={rootRef} className="contents">
            {referenceLabels.map((line) => {
                const y = scales.y(line.value)
                if (!isFinite(y) || y < dimensions.plotTop || y > dimensions.plotTop + dimensions.plotHeight) {
                    return null
                }
                const measuredLeft = captionLefts[line.key]
                const atEnd = measuredLeft === undefined && line.position === 'end'
                return (
                    <span
                        key={line.key}
                        data-attr={`spend-trajectory-reference-label-${line.key}`}
                        className={`absolute text-xs leading-none whitespace-nowrap font-semibold -translate-y-full ${
                            atEnd ? '-translate-x-full' : ''
                        } ${TONE_CLASS[line.tone]}`}
                        style={{
                            left: measuredLeft ?? (atEnd ? plotRight - LABEL_INSET : dimensions.plotLeft + LABEL_INSET),
                            top: y - LABEL_LINE_GAP,
                        }}
                    >
                        {line.text}
                    </span>
                )
            })}
            {markers.map((marker) => {
                const x = scales.x(marker.label)
                const y = scales.y(marker.value)
                if (x === undefined || !isFinite(x) || !isFinite(y)) {
                    return null
                }
                const color = series.find((s) => s.key === marker.seriesKey)?.color
                const textLeft =
                    marker.key === 'crossing'
                        ? x + CROSSING_TEXT_WIDTH > plotRight
                        : marker.key === 'end' || x - dimensions.plotLeft >= MIN_LEFT_TEXT_ROOM
                return (
                    <div key={marker.key} data-attr={`spend-trajectory-marker-${marker.key}`}>
                        <span
                            className="absolute size-1.5 rounded-full -translate-x-1/2 -translate-y-1/2"
                            style={{ left: x, top: y, background: color }}
                        />
                        <span
                            className={`absolute text-xs leading-none whitespace-nowrap font-semibold -translate-y-1/2 ${
                                textLeft ? '-translate-x-full' : ''
                            } ${TONE_CLASS[marker.tone]}`}
                            style={{ left: textLeft ? x - LABEL_GAP : x + LABEL_GAP, top: labelTop(y) }}
                        >
                            {marker.text}
                        </span>
                    </div>
                )
            })}
        </div>
    )
}
