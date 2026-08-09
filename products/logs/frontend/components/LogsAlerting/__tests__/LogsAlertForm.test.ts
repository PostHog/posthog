import { buildCheckPattern } from '../LogsAlertForm'

describe('buildCheckPattern', () => {
    it('marks the last datapoints-worth of checks as matched for valid inputs', () => {
        expect(buildCheckPattern(1, 5)).toEqual([false, false, false, false, true])
        expect(buildCheckPattern(3, 5)).toEqual([false, true, true, false, true])
        expect(buildCheckPattern(5, 5)).toEqual([true, true, true, true, true])
    })

    // Regression: while typing into the period/datapoints number inputs, transient values
    // (cleared field, negative, non-finite, or an oversized pasted number) used to reach
    // Array(periods) directly and throw "RangeError: Invalid array length".
    it.each([
        ['NaN periods', 1, NaN],
        ['negative periods', 1, -5],
        ['non-integer periods', 1, 2.5],
        ['huge periods', 1, Number.MAX_SAFE_INTEGER],
        ['Infinity periods', 1, Infinity],
        ['negative datapoints', -5, 5],
        ['NaN datapoints', NaN, 5],
    ])('does not throw for %s', (_name, datapoints, periods) => {
        expect(() => buildCheckPattern(datapoints, periods)).not.toThrow()
    })
})
