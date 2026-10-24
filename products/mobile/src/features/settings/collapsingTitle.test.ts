import { collapsingTitleTransform, type TitleGeometry } from './collapsingTitle'

const CHIP_WIDTH = 88
const GEOMETRY: TitleGeometry = { travel: 62.6, shift: CHIP_WIDTH + 12, endScale: 17 / 28, gap: 20, halfHeight: 19.6 }

describe('collapsingTitleTransform', () => {
    test.each([
        ['pull-down overscroll', -40, { translateX: 0, translateY: 0, scale: 1 }],
        ['rest', 0, { translateX: 0, translateY: 0, scale: 1 }],
        ['pinned', 62.6, { translateX: 100, translateY: -62.6, scale: 17 / 28 }],
        ['past the travel', 400, { translateX: 100, translateY: -62.6, scale: 17 / 28 }],
    ])('%s at scroll %s', (_label, scrollY, expected) => {
        const t = collapsingTitleTransform(scrollY, GEOMETRY)
        expect(t.translateX).toBeCloseTo(expected.translateX)
        expect(t.translateY).toBeCloseTo(expected.translateY)
        expect(t.scale).toBeCloseTo(expected.scale)
    })

    test('the title never enters the chip row while it still overlaps the chip horizontally', () => {
        for (let scrollY = 0; scrollY <= GEOMETRY.travel; scrollY += 0.5) {
            const t = collapsingTitleTransform(scrollY, GEOMETRY)
            // Rest box top is 0 and the chip row's bottom is at -gap; the title scales about its left center.
            const boxTop = GEOMETRY.halfHeight + t.translateY - GEOMETRY.halfHeight * t.scale
            if (boxTop < -GEOMETRY.gap) {
                expect(t.translateX).toBeGreaterThanOrEqual(CHIP_WIDTH)
            }
        }
    })
})
