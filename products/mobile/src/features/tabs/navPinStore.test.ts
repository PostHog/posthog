import { type NavPin, nextNavPins, replacedNavPin, sanitizedNavPins } from './navPinStore'

describe('navPinStore', () => {
    test.each<[string, readonly NavPin[], NavPin, boolean, readonly NavPin[]]>([
        ['pinning the second list replaces the first', ['replay'], 'errors', true, ['errors']],
        ['pinning a pinned list changes nothing', ['errors'], 'errors', true, ['errors']],
        ['unpinning empties the slot', ['errors'], 'errors', false, []],
    ])('%s', (_name, pins, pin, pinned, expected) => {
        expect(nextNavPins(pins, pin, pinned)).toEqual(expected)
    })

    test('names the list a new pin replaces, for the toast', () => {
        expect(replacedNavPin(['replay'], 'errors')).toBe('replay')
        expect(replacedNavPin(['errors'], 'errors')).toBeNull()
        expect(replacedNavPin([], 'errors')).toBeNull()
    })

    test('a saved list from another app version keeps only known pins, once each', () => {
        expect(sanitizedNavPins(['pulse', 'replay', 'replay', 'errors'])).toEqual(['replay'])
        expect(sanitizedNavPins('errors')).toEqual([])
    })
})
