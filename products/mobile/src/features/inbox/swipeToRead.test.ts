import { commitDistance, rowOffset } from './swipeToRead'

describe('swipe to read', () => {
    test.each([
        [400, 120],
        [320, 104],
    ])('commits a %ipt row after %ipt of travel', (width, distance) => {
        expect(commitDistance(width)).toBe(distance)
    })

    test.each([
        ['follows the finger to the right', 150, 150],
        ['follows the finger to the left', -150, -150],
        ['resists drag past the row width to the right', 400, 342.96],
        ['resists drag past the row width to the left', -400, -342.96],
    ] as const)('%s', (_name, translationX, expected) => {
        expect(rowOffset(translationX, 320)).toBeCloseTo(expected, 1)
    })
})
