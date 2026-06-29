import { ChartOverlayState, chartOverlayState } from './VisionInsightChart'

describe('chartOverlayState', () => {
    // `insightData` is always a truthy object from the selector, so the decision must hinge on `result`, not the object.
    const cases: [string, { result?: unknown } | null | undefined, boolean, ChartOverlayState][] = [
        ['null insightData while loading', null, true, 'loading'],
        ['null insightData settled (cancelled/never-loaded)', null, false, 'error'],
        ['truthy object with no result while loading', { result: undefined }, true, 'loading'],
        ['truthy object with no result settled', { result: undefined }, false, 'error'],
        ['loaded with rows', { result: [{ x: 1 }] }, false, 'none'],
        ['loaded but empty result', { result: [] }, false, 'none'],
        ['loaded, ignores a stale loading flag during refresh', { result: [{ x: 1 }] }, true, 'none'],
    ]

    it.each(cases)('%s', (_label, insightData, loading, expected) => {
        expect(chartOverlayState(insightData, loading)).toEqual(expected)
    })
})
