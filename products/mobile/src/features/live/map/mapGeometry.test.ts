import { fitMap, type HitPath, pickCountry, toMapPoint, WORLD_CROP } from './mapGeometry'

/** A 100 × 100 map-unit square at (1000, 500), standing in for a country's Skia path. */
const SQUARE: HitPath = { contains: (x, y) => x >= 1000 && x <= 1100 && y >= 500 && y <= 600 }

describe('map geometry', () => {
    test('a tap in the box maps back to the cropped map units', () => {
        const fit = fitMap(WORLD_CROP, 258)
        expect(fit.scale).toBeCloseTo(0.1)
        expect(fit.height).toBeCloseTo(115.6)
        expect(toMapPoint(fit, 0, 0)).toEqual({ x: 90, y: 16 })
        const corner = toMapPoint(fit, 258, fit.height)
        expect(corner.x).toBeCloseTo(2670)
        expect(corner.y).toBeCloseTo(1172)
    })

    test.each([
        ['inside the shape', { x: 1050, y: 550 }, 0, 'XX'],
        ['outside with no slop', { x: 1110, y: 550 }, 0, null],
        ['just outside, within the slop', { x: 1110, y: 550 }, 24, 'XX'],
        ['beyond the slop', { x: 1200, y: 550 }, 24, null],
    ])('a tap %s', (_name, point, slop, expected) => {
        expect(pickCountry([['XX', SQUARE]], point, slop)).toBe(expected)
    })

    test('a shape under the tap wins over an earlier shape within the slop', () => {
        const right: HitPath = { contains: (x, y) => x > 1100 && x <= 1200 && y >= 500 && y <= 600 }
        expect(
            pickCountry(
                [
                    ['XX', SQUARE],
                    ['YY', right],
                ],
                { x: 1102, y: 550 },
                24
            )
        ).toBe('YY')
    })
})
