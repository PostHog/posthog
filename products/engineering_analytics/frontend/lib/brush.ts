export interface TimeRange {
    start: number
    end: number
}

/** The lens initially matches the selected date range so the chart and page filter stay aligned. */
export function defaultFocus(tMin: number, tMax: number): TimeRange {
    return { start: tMin, end: tMax }
}

/** Preserves the range's width where possible, so a pan that hits an edge slides instead of shrinking. */
export function clampFocus(range: TimeRange, tMin: number, tMax: number, minSpanMs: number): TimeRange {
    const fullSpan = Math.max(0, tMax - tMin)
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

export function panFocus(range: TimeRange, deltaMs: number, tMin: number, tMax: number): TimeRange {
    return clampFocus({ start: range.start + deltaMs, end: range.end + deltaMs }, tMin, tMax, range.end - range.start)
}

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

export function pxToTime(px: number, width: number, tMin: number, tMax: number): number {
    if (width <= 0) {
        return tMin
    }
    const frac = Math.min(1, Math.max(0, px / width))
    return tMin + frac * (tMax - tMin)
}

export function timeToFrac(t: number, tMin: number, tMax: number): number {
    if (tMax <= tMin) {
        return 0
    }
    return Math.min(1, Math.max(0, (t - tMin) / (tMax - tMin)))
}
