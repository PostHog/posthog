import { buildCheckPattern } from '../LogsAlertForm'

describe('buildCheckPattern', () => {
    it.each([
        [1, 5, [false, false, false, false, true]],
        [3, 5, [false, true, true, false, true]],
        [5, 5, [true, true, true, true, true]],
    ])('builds the pattern for %i of %i checks', (datapoints, periods, expected) => {
        expect(buildCheckPattern(datapoints, periods)).toEqual(expected)
    })

    it.each([
        ['cleared periods', 1, NaN],
        ['negative periods', 1, -5],
        ['non-integer periods', 1, 2.5],
        ['huge periods', 1, Number.MAX_SAFE_INTEGER],
        ['infinite periods', 1, Infinity],
        ['cleared datapoints', NaN, 5],
        ['negative datapoints', -5, 5],
    ])('returns a valid pattern for %s', (_name, datapoints, periods) => {
        const result = buildCheckPattern(datapoints, periods)
        expect(result.length).toBeLessThanOrEqual(100)
        expect(result.every((value) => typeof value === 'boolean')).toBe(true)
    })
})
