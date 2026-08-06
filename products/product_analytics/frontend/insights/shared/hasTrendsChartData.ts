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
        return !!result.data && result.count !== 0
    })
}
