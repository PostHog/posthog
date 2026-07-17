import { hexToRGBA } from 'lib/utils/colors'

import { COMPARE_PREVIOUS_DIM_OPACITY, dimHexColor } from './compareDimming'

describe('compareDimming', () => {
    it('COMPARE_PREVIOUS_DIM_OPACITY is half opacity', () => {
        expect(COMPARE_PREVIOUS_DIM_OPACITY).toBe(0.5)
    })

    // Must match lib/utils' hexToRGBA for valid hex (incl. 3/8-digit forms); the one intentional
    // divergence is that a non-hex string is returned unchanged rather than producing rgba(NaN,...).
    it.each([
        { base: '#ff0000', expected: hexToRGBA('#ff0000', 0.5) },
        { base: '#f00', expected: hexToRGBA('#f00', 0.5) },
        { base: '#ff000080', expected: hexToRGBA('#ff000080', 0.5) },
        { base: 'var(--color-1)', expected: 'var(--color-1)' },
        { base: 'not-a-hex', expected: 'not-a-hex' },
    ])('dimHexColor($base) -> $expected', ({ base, expected }) => {
        expect(dimHexColor(base, 0.5)).toBe(expected)
    })

    it('respects the requested alpha', () => {
        expect(dimHexColor('#ffffff', 0.25)).toBe('rgba(255,255,255,0.25)')
    })
})
