import {
    formatRankingLift,
    formatRankingLiftComparison,
    rankingLiftBarFill,
    rankingLiftBarPercent,
    rankingStrength,
} from './rankingFormat'

describe('rankingFormat', () => {
    test.each([
        [0.04, '0.0x'],
        [1, '1.0x'],
        [2.74, '2.7x'],
        [9.94, '9.9x'],
        [9.96, '10x'],
        [12.4, '12x'],
    ])('formats a lift of %s as %s', (lift, expected) => {
        expect(formatRankingLift(lift)).toBe(expected)
    })

    test.each([
        [2.4, '2.4x more likely'],
        [1.06, '1.1x more likely'],
        [1.04, '1.0x as likely'],
        [0.96, '1.0x as likely'],
        [0.6, '0.6x as likely'],
        [12.4, '12x more likely'],
    ])('labels a lift of %s on the pill as %s', (lift, expected) => {
        expect(formatRankingLiftComparison(lift)).toBe(expected)
    })

    test.each([
        [0, 0],
        [0.05, 0],
        [0.1, 0],
        [1, 50],
        [10, 100],
        [40, 100],
    ])('places a lift of %s at %s% of the bar', (lift, expected) => {
        expect(rankingLiftBarPercent(lift)).toBeCloseTo(expected)
    })

    test.each([
        [1, 50, 0],
        [10, 50, 50],
        [40, 50, 50],
        [Math.sqrt(10), 50, 25],
        [0.1, 0, 50],
        [0.05, 0, 50],
        [1 / Math.sqrt(10), 25, 25],
    ])('fills the bar for a lift of %s from %s% with a width of %s%', (lift, left, width) => {
        const fill = rankingLiftBarFill(lift)
        expect(fill.left).toBeCloseTo(left)
        expect(fill.width).toBeCloseTo(width)
    })

    test.each([
        [3.1, 'very_likely'],
        [2, 'very_likely'],
        [1.99, 'likely'],
        [1.25, 'likely'],
        [1, 'average'],
        [0.8, 'unlikely'],
        [0.2, 'unlikely'],
    ])('reads a lift of %s as %s', (lift, expected) => {
        expect(rankingStrength(lift)).toBe(expected)
    })

    it('places a lift and its inverse at equal distances from 1x', () => {
        expect(rankingLiftBarPercent(4) - 50).toBeCloseTo(50 - rankingLiftBarPercent(0.25))
    })
})
