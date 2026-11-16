import { mapFill } from './mapColors'

const COLORS = { segmentEmpty: '#DADAD5', blue: '#1D4AFF' }

describe('mapFill', () => {
    test.each([
        ['the leading country is the theme blue', 1, '#1d4aff'],
        ['the fewest visitors keep the 30% floor toward blue', 0, '#a1afe2'],
        ['half the leader mixes 65% of the way', 0.5, '#5f7cf0'],
        ['a ratio above 1 stays blue', 3, '#1d4aff'],
        ['a ratio that is not a number falls to the floor', Number.NaN, '#a1afe2'],
    ])('%s', (_name, ratio, expected) => {
        expect(mapFill(COLORS, ratio)).toBe(expected)
    })

    test('a token that is not a hex color falls back to blue', () => {
        expect(mapFill({ segmentEmpty: 'rgba(0,0,0,0.1)', blue: '#1D4AFF' }, 0.5)).toBe('#1D4AFF')
    })
})
