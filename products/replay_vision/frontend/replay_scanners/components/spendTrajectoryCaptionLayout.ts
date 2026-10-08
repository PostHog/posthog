import type { SpendMarkerTone, SpendReferenceLabel } from './spendTrajectoryTransforms'

export const LABEL_CLEARANCE = 12
export const LABEL_HEIGHT = 12
export const LABEL_ABOVE = 6
export const LABEL_INSET = 4
const COLLISION_PADDING = 2

export const SPEND_TONE_CLASS: Record<SpendMarkerTone, string> = {
    default: 'text-primary',
    muted: 'text-muted',
    danger: 'text-danger',
}

export interface Box {
    left: number
    right: number
    top: number
    bottom: number
}

export type CaptionLefts = Partial<Record<SpendReferenceLabel['key'], number>>

export function toBox(rect: DOMRect, origin: DOMRect): Box {
    return {
        left: rect.left - origin.left - COLLISION_PADDING,
        right: rect.right - origin.left + COLLISION_PADDING,
        top: rect.top - origin.top - COLLISION_PADDING,
        bottom: rect.bottom - origin.top + COLLISION_PADDING,
    }
}

export function overlaps(a: Box, b: Box): boolean {
    return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom
}

// Labels sit above their anchor. Below a point is the filled area and the rising curve, so a label
// blocked by a reference line climbs past it instead of dropping into the fill.
export function resolveLabelTop(anchorY: number, referenceYs: number[]): number {
    let candidate = anchorY - LABEL_ABOVE
    for (const reference of referenceYs) {
        if (Math.abs(candidate - reference) < LABEL_CLEARANCE) {
            candidate = reference - LABEL_CLEARANCE
        }
    }
    return Math.max(candidate, LABEL_HEIGHT / 2)
}

interface CaptionPlacement {
    strip: Box
    width: number
    position: SpendReferenceLabel['position']
    markerBoxes: Box[]
    lineStart: number
    lineEnd: number
}

// Preferred end first, then the other end, then the widest gaps between markers along the line.
export function resolveCaptionLeft({
    strip,
    width,
    position,
    markerBoxes,
    lineStart,
    lineEnd,
}: CaptionPlacement): number {
    const boxAt = (left: number): Box => ({
        ...strip,
        left: left - COLLISION_PADDING,
        right: left + width + COLLISION_PADDING,
    })
    const atStart = lineStart
    const atEnd = lineEnd - width
    const candidates = position === 'end' ? [atEnd, atStart] : [atStart, atEnd]
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
    return candidates.find((left) => !markerBoxes.some((marker) => overlaps(marker, boxAt(left)))) ?? candidates[0]
}

export function measureCaptionLefts(
    root: HTMLElement,
    referenceLabels: SpendReferenceLabel[],
    lineStart: number,
    lineEnd: number
): CaptionLefts | null {
    const origin = root.parentElement?.getBoundingClientRect()
    if (!origin) {
        return null
    }
    const markerBoxes = Array.from(
        root.querySelectorAll<HTMLElement>('[data-attr^="spend-trajectory-marker-"] > span:last-child')
    ).map((el) => toBox(el.getBoundingClientRect(), origin))
    const lefts: CaptionLefts = {}
    for (const line of referenceLabels) {
        const el = root.querySelector<HTMLElement>(`[data-attr="spend-trajectory-reference-label-${line.key}"]`)
        if (!el) {
            continue
        }
        const measured = el.getBoundingClientRect()
        lefts[line.key] = resolveCaptionLeft({
            strip: toBox(measured, origin),
            width: measured.width,
            position: line.position,
            markerBoxes,
            lineStart,
            lineEnd,
        })
    }
    return lefts
}
