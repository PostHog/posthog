import type { IndexedTrendResult } from 'scenes/trends/types'

// Gate the empty state on the whole result set, not just the first series — trendsDataLogic
// re-sorts and interleaves results for compare mode, breakdown ordering, and unstacked bars, so
// index 0 isn't a stable "does this tile have data" signal.
export function hasTrendsChartData(indexedResults: IndexedTrendResult[] | undefined): boolean {
    if (!indexedResults?.length) {
        return false
    }
    return indexedResults.some((result: IndexedTrendResult) => {
        if (Number.isFinite(result.aggregated_value) && result.aggregated_value !== 0) {
            return true
        }
        // Check the array that actually gets plotted, not the scalar `count`. For a formula series
        // the backend computes `count` as a ratio-of-sums over whole-period totals, which can net to
        // zero while the per-interval `data` it plots is clearly non-zero (e.g. `A - B` totals cancel
        // but individual buckets differ), so trusting `count` blanks a chart that has real points.
        return !!result.data && result.data.some((value) => Number.isFinite(value) && value !== 0)
    })
}
