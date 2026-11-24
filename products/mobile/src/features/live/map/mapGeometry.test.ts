import { fitMap, type MapTransform, mapTransform } from './mapGeometry'

/** Applies a Skia transform list the way Skia does: the matrices multiply left to right, so the last one acts first. */
function apply(transform: MapTransform, x: number, y: number): { x: number; y: number } {
    const [{ translateX }, { translateY }, { scale }] = transform
    return { x: x * scale + translateX, y: y * scale + translateY }
}

describe('map geometry', () => {
    test('the drawing transform makes the crop fill the box', () => {
        const fit = fitMap(258)
        expect(fit.scale).toBeCloseTo(0.1)
        expect(apply(mapTransform(fit), 90, 16)).toEqual({ x: 0, y: 0 })
    })
})
