import { sparklineBarHeight } from './sparklineMath'

describe('sparklineBarHeight', () => {
    test.each([
        [120, 120, 32],
        [104, 120, 28],
        [36, 120, 10],
        [2, 120, 2],
        [0, 120, 2],
        [500, 120, 32],
        [5, 0, 2],
        [Number.NaN, 120, 2],
    ])('value %s of max %s is %spt tall', (value, max, expected) => {
        expect(sparklineBarHeight(value, max)).toBe(expected)
    })
})
