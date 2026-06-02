// In the aggregated (horizontal) bar value chart each breakdown value gets its own bar, so a
// high-cardinality breakdown turns into hundreds of stacked bars that blow out the chart height
// and freeze the main thread. Cap the number of bars actually drawn; the full result set stays
// browsable in the results table below the chart.
export const MAX_CHART_DATASETS = 150

// Returns the prefix of `results` containing at most `limit` visible (non-hidden) entries.
// Hidden entries — which hog-charts keeps as `excluded` series — are preserved within the
// prefix but don't count toward the limit, mirroring the legacy behavior of capping only the
// datasets that are actually rendered.
export function capResultsToChartLimit<R>(
    results: readonly R[],
    getHidden?: (r: R, index: number) => boolean,
    limit: number = MAX_CHART_DATASETS
): R[] {
    if (results.length <= limit) {
        return results.slice()
    }
    const capped: R[] = []
    let visibleCount = 0
    for (let index = 0; index < results.length; index++) {
        const hidden = getHidden ? getHidden(results[index], index) : false
        if (visibleCount >= limit) {
            break
        }
        if (!hidden) {
            visibleCount++
        }
        capped.push(results[index])
    }
    return capped
}
