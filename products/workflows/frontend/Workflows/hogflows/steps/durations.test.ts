import { isDuration, isSignedDuration, parseDuration, splitPartialDuration } from './durations'

describe('durations', () => {
    // A cleared field emits the unit on its own. That once reached the API as conversion.window and
    // failed the save, so the storable-value matchers have to keep rejecting it.
    test.each([
        ['7d', true],
        ['12h', true],
        ['45s', true],
        ['1.5h', true],
        ['.5m', true],
        ['d', false],
        ['', false],
        ['5.d', false],
        ['-5d', false],
        ['7 d', false],
        ['7dd', false],
        ['P30D', false],
        ['٥d', false],
    ])('isDuration(%p) is %p', (value, expected) => {
        expect(isDuration(value)).toBe(expected)
    })

    test.each([
        ['-5d', true],
        ['5d', true],
        ['-.5m', true],
        ['-d', false],
        ['--5d', false],
    ])('isSignedDuration(%p) is %p', (value, expected) => {
        expect(isSignedDuration(value)).toBe(expected)
    })

    it('keeps the amount as written so a round trip does not restyle it', () => {
        expect(parseDuration('1.50d')).toMatchObject({ amountText: '1.50', amount: 1.5, unit: 'd', negative: false })
        expect(parseDuration('-7h')).toMatchObject({ amountText: '7', unit: 'h', negative: true })
        expect(parseDuration('d')).toBeNull()
    })

    it('splits a field mid-edit, including the cleared amount', () => {
        expect(splitPartialDuration('d')).toEqual({ amountText: '', unit: 'd' })
        expect(splitPartialDuration('12h')).toEqual({ amountText: '12', unit: 'h' })
        expect(splitPartialDuration('nonsense')).toEqual({ amountText: '', unit: 'm' })
    })
})
