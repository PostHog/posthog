import { formatFreezeExposureDuration } from 'products/experiments/frontend/freezeExposureDuration'

describe('formatFreezeExposureDuration', () => {
    test.each([
        [0.5, 'a few seconds'],
        [4.9, 'a few seconds'],
        [7.4, 'about 7 seconds'],
        [9.6, 'about 10 seconds'],
        [23, 'about 25 seconds'],
        [58, 'about 1 minute'],
        [73, 'about 1 minute 10 seconds'],
        [122, 'about 2 minutes'],
    ])('%s seconds reads as "%s"', (seconds, expected) => {
        expect(formatFreezeExposureDuration(seconds)).toBe(expected)
    })
})
