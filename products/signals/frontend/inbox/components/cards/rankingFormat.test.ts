import { formatRankingLift, rankingLiftBarPercent } from './rankingFormat'

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
        [0, 0],
        [0.05, 0],
        [0.1, 0],
        [1, 50],
        [10, 100],
        [40, 100],
    ])('places a lift of %s at %s% of the bar', (lift, expected) => {
        expect(rankingLiftBarPercent(lift)).toBeCloseTo(expected)
    })

    it('places a lift and its inverse at equal distances from 1x', () => {
        expect(rankingLiftBarPercent(4) - 50).toBeCloseTo(50 - rankingLiftBarPercent(0.25))
    })
})
