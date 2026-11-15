import { fitMap, type HitPath, type MapTransform, mapTransform, pickCountry, toMapPoint } from './mapGeometry'

function square(left: number, top: number, size: number): HitPath {
    return {
        contains: (x, y) => x >= left && x <= left + size && y >= top && y <= top + size,
        getBounds: () => ({ width: size, height: size }),
    }
}

/** Applies a Skia transform list the way Skia does: the matrices multiply left to right, so the last one acts first. */
function apply(transform: MapTransform, x: number, y: number): { x: number; y: number } {
    const [{ translateX }, { translateY }, { scale }] = transform
    return { x: x * scale + translateX, y: y * scale + translateY }
}

const VISITED = new Set(['XX', 'YY'])
const hasVisitors = (code: string): boolean => VISITED.has(code)

describe('map geometry', () => {
    test('the drawing transform and the tap inverse agree, and the crop fills the box', () => {
        const fit = fitMap(258)
        expect(fit.scale).toBeCloseTo(0.1)
        expect(apply(mapTransform(fit), 90, 16)).toEqual({ x: 0, y: 0 })
        const drawn = apply(mapTransform(fit), 1380, 594)
        const back = toMapPoint(fit, drawn.x, drawn.y)
        expect(back.x).toBeCloseTo(1380)
        expect(back.y).toBeCloseTo(594)
    })

    test.each([
        ['inside a shape with visitors', [['XX', square(1000, 500, 100)]], { x: 1050, y: 550 }, 0, 'XX'],
        ['on the sea with no slop', [['XX', square(1000, 500, 100)]], { x: 1110, y: 550 }, 0, null],
        ['on the sea within the slop', [['XX', square(1000, 500, 100)]], { x: 1110, y: 550 }, 24, 'XX'],
        ['on the sea beyond the slop', [['XX', square(1000, 500, 100)]], { x: 1200, y: 550 }, 24, null],
        [
            'inside a shape without visitors, next to one with visitors within the slop',
            [
                ['XX', square(1000, 500, 100)],
                ['ZZ', square(1101, 500, 100)],
            ],
            { x: 1105, y: 550 },
            24,
            null,
        ],
        [
            'inside a shape without visitors smaller than the slop',
            [
                ['XX', square(1000, 500, 100)],
                ['ZZ', square(1101, 545, 10)],
            ],
            { x: 1105, y: 550 },
            24,
            'XX',
        ],
        [
            'inside a shape with visitors, with an earlier shape within the slop',
            [
                ['XX', square(1000, 500, 100)],
                ['YY', square(1101, 500, 100)],
            ],
            { x: 1102, y: 550 },
            24,
            'YY',
        ],
    ] as [string, [string, HitPath][], { x: number; y: number }, number, string | null][])(
        'a tap %s',
        (_name, paths, point, slop, expected) => {
            expect(pickCountry(paths, hasVisitors, point, slop)).toBe(expected)
        }
    )
})
