// Pure geometry for the run-activity chart's focus lens — a context strip that shows the whole loaded
// window with a draggable lens selecting the sub-range the scatter and band zoom into. The default lens is
// the most recent 24h (the live view), pannable back over older days and resizable up to the full window.
// Kept here, DOM-free, so the math (default placement, clamping, panning, resizing, px<->time) is unit-tested
// without rendering.

export interface TimeRange {
    start: number
    end: number
}

/** The lens's initial position: the most recent `lensMs` of the window, or the whole window when it's
 *  already shorter than the lens (nothing to pan over). */
export function defaultFocus(tMin: number, tMax: number, lensMs: number): TimeRange {
    if (tMax - tMin <= lensMs) {
        return { start: tMin, end: tMax }
    }
    return { start: tMax - lensMs, end: tMax }
}

/** Keep a range inside [tMin, tMax] and at least `minSpanMs` wide, preserving its width where possible so a
 *  pan that hits an edge slides rather than shrinks. */
export function clampFocus(range: TimeRange, tMin: number, tMax: number, minSpanMs: number): TimeRange {
    const fullSpan = Math.max(0, tMax - tMin)
    // Never wider than the window, never narrower than the floor.
    const span = Math.min(Math.max(range.end - range.start, minSpanMs), Math.max(fullSpan, minSpanMs))
    let start = range.start
    if (start + span > tMax) {
        start = tMax - span
    }
    if (start < tMin) {
        start = tMin
    }
    return { start, end: start + span }
}

/** Shift a range by `deltaMs`, keeping its width and staying within bounds (a pan, not a resize). */
export function panFocus(range: TimeRange, deltaMs: number, tMin: number, tMax: number): TimeRange {
    return clampFocus({ start: range.start + deltaMs, end: range.end + deltaMs }, tMin, tMax, range.end - range.start)
}

/** Drag one edge of a range to `timeMs`, keeping start<end by at least `minSpanMs` and staying in bounds. */
export function resizeFocus(
    range: TimeRange,
    edge: 'start' | 'end',
    timeMs: number,
    tMin: number,
    tMax: number,
    minSpanMs: number
): TimeRange {
    const t = Math.min(Math.max(timeMs, tMin), tMax)
    if (edge === 'start') {
        return { start: Math.min(t, range.end - minSpanMs), end: range.end }
    }
    return { start: range.start, end: Math.max(t, range.start + minSpanMs) }
}

/** Map a pixel offset within a strip of `width` px to a timestamp in [tMin, tMax]. */
export function pxToTime(px: number, width: number, tMin: number, tMax: number): number {
    if (width <= 0) {
        return tMin
    }
    const frac = Math.min(1, Math.max(0, px / width))
    return tMin + frac * (tMax - tMin)
}

/** Fraction (0..1) of the way `t` sits through [tMin, tMax], for positioning the lens on the strip. */
export function timeToFrac(t: number, tMin: number, tMax: number): number {
    if (tMax <= tMin) {
        return 0
    }
    return Math.min(1, Math.max(0, (t - tMin) / (tMax - tMin)))
}
