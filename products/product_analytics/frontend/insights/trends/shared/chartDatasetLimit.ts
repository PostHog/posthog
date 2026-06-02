// In the aggregated (horizontal) bar value chart each breakdown value gets its own bar, so a
// high-cardinality breakdown turns into hundreds of stacked bars that blow out the chart height
// and freeze the main thread. Cap the number of bars actually drawn; the full result set stays
// browsable in the results table below the chart.
//
// Mirrors the legacy Chart.js cap in frontend/src/scenes/insights/views/LineGraph/LineGraph.tsx —
// keep the two values in sync until that renderer is retired (the layering forbids a shared import).
export const MAX_CHART_DATASETS = 150

// Returns the first `limit` results. Callers are expected to have already dropped hidden entries,
// so this is a plain prefix of the series that will actually be drawn — matching the legacy
// `visibleDatasets.slice(0, MAX_CHART_DATASETS)` semantics.
export function capResultsToChartLimit<R>(results: readonly R[], limit: number = MAX_CHART_DATASETS): R[] {
    return results.slice(0, limit)
}
