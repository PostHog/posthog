import { clampSegmentWidths, quotaMeterWidths } from './QuotaMeterBar'

describe('QuotaMeterBar', () => {
    describe('clampSegmentWidths', () => {
        it('passes widths through when they fit', () => {
            expect(clampSegmentWidths([40, 20, 10])).toEqual([40, 20, 10])
        })

        it('truncates the overflowing segment and zeroes the rest', () => {
            expect(clampSegmentWidths([60, 30, 50])).toEqual([60, 30, 10])
            expect(clampSegmentWidths([80, 120, 50])).toEqual([80, 20, 0])
        })

        it('zeroes later segments when the bar is already saturated', () => {
            expect(clampSegmentWidths([100, 30, 10])).toEqual([100, 0, 0])
            expect(clampSegmentWidths([150, 30])).toEqual([100, 0])
        })

        it('floors negative widths at zero without consuming headroom', () => {
            expect(clampSegmentWidths([-10, 50])).toEqual([0, 50])
        })
    })

    describe('quotaMeterWidths', () => {
        it.each([
            ['free slice within spend', 50, 20, [30], [20, 30, 30]],
            ['free slice clamped to spend so the free chip cannot outsize actual usage', 30, 80, [10], [30, 0, 10]],
            ['negative free slice floored at zero', 40, -5, [10], [0, 40, 10]],
        ])('%s', (_name, usedPct, usedFreePct, projected, expected) => {
            expect(quotaMeterWidths(usedPct, usedFreePct, projected)).toEqual(expected)
        })
    })
})
