import { capResultsToChartLimit, MAX_CHART_DATASETS } from './chartDatasetLimit'

describe('capResultsToChartLimit', () => {
    const makeResults = (count: number): { id: number }[] => Array.from({ length: count }, (_, id) => ({ id }))

    it('returns the input untouched when at or below the limit', () => {
        const results = makeResults(MAX_CHART_DATASETS)
        const capped = capResultsToChartLimit(results)

        expect(capped).toHaveLength(MAX_CHART_DATASETS)
        expect(capped).toEqual(results)
    })

    it('caps at MAX_CHART_DATASETS by default', () => {
        const capped = capResultsToChartLimit(makeResults(MAX_CHART_DATASETS + 250))

        expect(capped).toHaveLength(MAX_CHART_DATASETS)
        expect(capped[0].id).toBe(0)
        expect(capped[capped.length - 1].id).toBe(MAX_CHART_DATASETS - 1)
    })

    it('respects a custom limit', () => {
        const capped = capResultsToChartLimit(makeResults(10), 3)

        expect(capped.map((r) => r.id)).toEqual([0, 1, 2])
    })

    it('returns a copy so callers can mutate without touching the source', () => {
        const results = makeResults(2)
        const capped = capResultsToChartLimit(results)

        expect(capped).not.toBe(results)
    })
})
