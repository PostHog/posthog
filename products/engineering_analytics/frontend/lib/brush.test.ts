import { clampFocus, defaultFocus, panFocus, pxToTime, resizeFocus, timeToFrac } from './brush'

const HOUR = 3_600_000
const DAY = 24 * HOUR

describe('brush geometry', () => {
    it('defaultFocus picks the most recent lens-width, or the whole window when shorter', () => {
        // 7-day window, 24h lens → most recent day.
        expect(defaultFocus(0, 7 * DAY, DAY)).toEqual({ start: 6 * DAY, end: 7 * DAY })
        // Window already shorter than the lens → no sub-range to pan, focus the whole thing.
        expect(defaultFocus(0, 6 * HOUR, DAY)).toEqual({ start: 0, end: 6 * HOUR })
    })

    it('clampFocus slides a range back inside bounds while preserving its width', () => {
        // A day-wide range pushed past the right edge slides left to fit, keeping its width.
        expect(clampFocus({ start: 7 * DAY, end: 8 * DAY }, 0, 7 * DAY, HOUR)).toEqual({
            start: 6 * DAY,
            end: 7 * DAY,
        })
        // Past the left edge slides right.
        expect(clampFocus({ start: -DAY, end: 0 }, 0, 7 * DAY, HOUR)).toEqual({ start: 0, end: DAY })
    })

    it('clampFocus caps width at the window and floors it at the minimum span', () => {
        // Wider than the window → clamped to the whole window.
        expect(clampFocus({ start: -DAY, end: 9 * DAY }, 0, 7 * DAY, HOUR)).toEqual({ start: 0, end: 7 * DAY })
        // Narrower than the floor → widened to the floor.
        expect(clampFocus({ start: DAY, end: DAY + 60_000 }, 0, 7 * DAY, HOUR).end).toBe(DAY + HOUR)
    })

    it('panFocus shifts within bounds and slides (not shrinks) at an edge', () => {
        const range = { start: 3 * DAY, end: 4 * DAY }
        expect(panFocus(range, DAY, 0, 7 * DAY)).toEqual({ start: 4 * DAY, end: 5 * DAY })
        // Panning past the right edge slides flush to it, keeping the day width.
        expect(panFocus(range, 10 * DAY, 0, 7 * DAY)).toEqual({ start: 6 * DAY, end: 7 * DAY })
    })

    it('resizeFocus drags one edge but never crosses the other past the minimum span', () => {
        const range = { start: 2 * DAY, end: 5 * DAY }
        expect(resizeFocus(range, 'start', 3 * DAY, 0, 7 * DAY, HOUR)).toEqual({ start: 3 * DAY, end: 5 * DAY })
        // Dragging start past end is capped to end - minSpan.
        expect(resizeFocus(range, 'start', 6 * DAY, 0, 7 * DAY, HOUR)).toEqual({ start: 5 * DAY - HOUR, end: 5 * DAY })
    })

    it('pxToTime and timeToFrac are inverse mappings, clamped to the strip', () => {
        expect(pxToTime(500, 1000, 0, 7 * DAY)).toBe(3.5 * DAY)
        expect(pxToTime(-50, 1000, 0, 7 * DAY)).toBe(0) // clamps below 0
        expect(timeToFrac(3.5 * DAY, 0, 7 * DAY)).toBe(0.5)
        expect(timeToFrac(0, 0, 0)).toBe(0) // degenerate window doesn't divide by zero
    })
})
