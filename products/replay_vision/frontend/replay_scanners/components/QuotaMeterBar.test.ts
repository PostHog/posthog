import { fitSegmentWidths, meterScale, quotaMeterWidths } from './QuotaMeterBar'

describe('QuotaMeterBar', () => {
    describe('fitSegmentWidths', () => {
        it('passes widths through when they fit under the limit', () => {
            expect(fitSegmentWidths([40, 20, 10])).toEqual([40, 20, 10])
        })

        it('rescales every segment proportionally once the total overshoots', () => {
            expect(fitSegmentWidths([100, 50, 50])).toEqual([50, 25, 25])
        })

        it('keeps an overshooting segment visible when little headroom is left', () => {
            // The whole point of rescaling: 5% of headroom must not swallow a segment six times its size.
            const [used, backfill] = fitSegmentWidths([95, 30])
            expect(backfill).toBeGreaterThan(used / 4)
        })

        it('floors negative widths at zero without shrinking the rest', () => {
            expect(fitSegmentWidths([-10, 50])).toEqual([0, 50])
        })
    })

    describe('meterScale', () => {
        it.each([
            ['stays at the limit when segments fit', [40, 20], 100],
            ['grows to the total once segments overshoot', [80, 70], 150],
            ['ignores negative segments', [120, -20], 120],
        ])('%s', (_name, pcts, expected) => {
            expect(meterScale(pcts)).toEqual(expected)
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
