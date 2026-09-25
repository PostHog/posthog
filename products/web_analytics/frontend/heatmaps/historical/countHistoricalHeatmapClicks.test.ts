import { countHistoricalHeatmapClicks } from './countHistoricalHeatmapClicks'

describe('countHistoricalHeatmapClicks', () => {
    const clicks = [
        { x: 320, y: 330, count: 20 },
        { x: 336, y: 330, count: 3 },
        { x: 344, y: 330, count: 2 },
        { x: 1000, y: 1000, count: 8 },
    ]

    it.each([1, 0.5, 0.25, 383 / 1440])('counts nearby recorded clicks at scale %s', (scale) => {
        expect(
            countHistoricalHeatmapClicks(clicks, { x: 233 + 320 * scale - 233, y: 253 + 330 * scale - 253 }, scale)
        ).toBe(25)
        expect(countHistoricalHeatmapClicks(clicks, { x: 1000 * scale, y: 1000 * scale }, scale)).toBe(8)
        expect(countHistoricalHeatmapClicks(clicks, { x: 600 * scale, y: 600 * scale }, scale)).toBe(0)
    })
})
