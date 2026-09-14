import { formatValue, readUnit } from './suggestionEvidence'

describe('suggestionEvidence', () => {
    it.each([
        ['a rate', 0.0865, 'rate' as const, '8.6%'],
        ['a rate of zero', 0, 'rate' as const, '0.0%'],
        ['a rate of one', 1, 'rate' as const, '100.0%'],
        // The regression: read as a rate, one complaint reads as every message.
        ['a count of one', 1, 'count' as const, '1'],
        ['a count', 240, 'count' as const, '240'],
        // A suggestion written before the unit contract says nothing, so neither does the panel.
        ['no unit', 0.0865, null, '0.0865'],
    ])('formats %s', (_name, value, unit, expected) => {
        expect(formatValue(value, unit)).toBe(expected)
    })

    it('has nothing to show for a value that is not a number', () => {
        expect(formatValue(null, 'rate')).toBeNull()
        expect(formatValue('8.65%', 'rate')).toBeNull()
    })

    it.each([
        ['rate', 'rate'],
        ['count', 'count'],
        ['percent', null],
        [undefined, null],
    ])('reads the unit %s', (raw, expected) => {
        expect(readUnit(raw)).toBe(expected)
    })
})
