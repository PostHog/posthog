import { capResultsToChartLimit, MAX_CHART_DATASETS } from './chartDatasetLimit'

describe('capResultsToChartLimit', () => {
    const makeResults = (count: number): { id: number }[] => Array.from({ length: count }, (_, id) => ({ id }))

    it('returns the input untouched when at or below the limit', () => {
        const results = makeResults(MAX_CHART_DATASETS)
        const capped = capResultsToChartLimit(results)

        expect(capped).toHaveLength(MAX_CHART_DATASETS)
        expect(capped).toEqual(results)
    })

    it('caps at MAX_CHART_DATASETS visible series by default', () => {
        const capped = capResultsToChartLimit(makeResults(MAX_CHART_DATASETS + 250))

        expect(capped).toHaveLength(MAX_CHART_DATASETS)
        expect(capped[0].id).toBe(0)
        expect(capped[capped.length - 1].id).toBe(MAX_CHART_DATASETS - 1)
    })

    it('respects a custom limit', () => {
        const capped = capResultsToChartLimit(makeResults(10), undefined, 3)

        expect(capped.map((r) => r.id)).toEqual([0, 1, 2])
    })

    it('counts only visible (non-hidden) entries toward the limit', () => {
        // Every other entry is hidden — hidden ones are preserved within the prefix but
        // don't count, so the prefix grows until it contains `limit` visible entries.
        const results = makeResults(20)
        const getHidden = (_r: { id: number }, index: number): boolean => index % 2 === 1

        const capped = capResultsToChartLimit(results, getHidden, 3)

        // Visible at indices 0, 2, 4 → prefix must reach index 4 (ids 0..4).
        expect(capped.map((r) => r.id)).toEqual([0, 1, 2, 3, 4])
        expect(capped.filter((_r, i) => i % 2 === 0)).toHaveLength(3)
    })

    it('returns a copy so callers can mutate without touching the source', () => {
        const results = makeResults(2)
        const capped = capResultsToChartLimit(results)

        expect(capped).not.toBe(results)
    })
})
