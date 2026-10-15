import { commitDistance, rowOffset } from './swipeToRead'

describe('swipe to read', () => {
    test.each([
        [400, 120],
        [320, 104],
    ])('commits a %ipt row after %ipt of travel', (width, distance) => {
        expect(commitDistance(width)).toBe(distance)
    })

    test.each([
        ['follows the finger toward a rightward action', 150, 1, 150],
        ['follows the finger toward a leftward action', -150, -1, -150],
        ['holds the row back on the left when the action is on the right', -300, 1, -11.19],
        ['holds the row back on the right when the action is on the left', 300, -1, 11.19],
        ['resists drag past the row width', 400, 1, 342.96],
    ] as const)('%s', (_name, translationX, direction, expected) => {
        expect(rowOffset(translationX, direction, 320)).toBeCloseTo(expected, 1)
    })
})
