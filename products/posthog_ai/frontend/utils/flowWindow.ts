/** Rows a flow-mode thread renders at once when it opens or receives a bulk append. */
export const FLOW_INITIAL_ROWS = 24
/** An append of more rows than this renders only its newest rows at once. */
export const FLOW_BULK_APPEND_ROWS = 48

/** A half-open `[from, to)` range of row indexes. */
export type FlowRange = readonly [number, number]

/**
 * Which rows of a flow-mode thread are in the DOM. `holes` are the ranges not rendered yet, sorted
 * and disjoint. A fill step renders rows from the end of the last hole, so the rows nearest the
 * newest content arrive first.
 */
export interface FlowWindow {
    length: number
    firstKey: string | null
    holes: readonly FlowRange[]
    /** Counts fill steps, so the scroll keeper can tell a fill commit from any other commit. */
    fillStep: number
    /** Changes when a different thread replaces the rows. */
    generation: number
}

function openWindow(length: number, firstKey: string | null, previous: FlowWindow | null): FlowWindow {
    const tailStart = Math.max(0, length - FLOW_INITIAL_ROWS)
    return {
        length,
        firstKey,
        holes: tailStart > 0 ? [[0, tailStart]] : [],
        fillStep: previous?.fillStep ?? 0,
        generation: (previous?.generation ?? 0) + 1,
    }
}

/**
 * Computes the window for the current rows from the previous window. Returns `previous` itself while
 * the row count and the first row stay the same, so a caller can compare by identity.
 */
export function deriveFlowWindow<T>(
    previous: FlowWindow | null,
    items: readonly T[],
    getItemKey: (item: T, index: number) => string
): FlowWindow {
    const length = items.length
    const firstKey = length > 0 ? getItemKey(items[0], 0) : null
    if (previous && previous.length === length && previous.firstKey === firstKey) {
        return previous
    }
    if (!previous || previous.length === 0 || previous.firstKey !== firstKey) {
        return openWindow(length, firstKey, previous)
    }
    const holes: [number, number][] = []
    for (const [from, to] of previous.holes) {
        const end = Math.min(to, length)
        if (from < end) {
            holes.push([from, end])
        }
    }
    const appendedFrom = previous.length
    const appendedTo = length - FLOW_INITIAL_ROWS
    if (length - previous.length > FLOW_BULK_APPEND_ROWS && appendedFrom < appendedTo) {
        const last = holes.at(-1)
        if (last && last[1] === appendedFrom) {
            last[1] = appendedTo
        } else {
            holes.push([appendedFrom, appendedTo])
        }
    }
    return { ...previous, length, firstKey, holes }
}

/** Renders up to `rows` more rows from the end of the last hole. */
export function fillFlowWindow(window: FlowWindow, rows: number): FlowWindow {
    const last = window.holes.at(-1)
    if (!last) {
        return window
    }
    const [from, to] = last
    const end = Math.max(from, to - rows)
    const holes = window.holes.slice(0, -1)
    if (from < end) {
        holes.push([from, end])
    }
    return { ...window, holes, fillStep: window.fillStep + 1 }
}

/** The rendered ranges, in order: everything outside the holes. */
export function renderedFlowRanges(window: FlowWindow): FlowRange[] {
    const ranges: FlowRange[] = []
    let cursor = 0
    for (const [from, to] of window.holes) {
        if (cursor < from) {
            ranges.push([cursor, from])
        }
        cursor = to
    }
    if (cursor < window.length) {
        ranges.push([cursor, window.length])
    }
    return ranges
}
