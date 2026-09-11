import type { MetricsQueryPoint, MetricsQuerySeries, MetricsReducer } from '~/queries/schema/schema-general'

/** The reducers a caller may ask for. `reduceSeries` returns `null` when a series has no
 * non-null point, so a panel can show "No data" instead of a misleading 0. */
export function reduceSeries(points: MetricsQueryPoint[], reducer: MetricsReducer): number | null {
    const values = points.map((p) => p.value).filter((v): v is number => v !== null && v !== undefined)
    if (values.length === 0) {
        return null
    }
    switch (reducer) {
        case 'last':
            return values[values.length - 1]
        case 'mean':
            return values.reduce((a, b) => a + b, 0) / values.length
        case 'min':
            return Math.min(...values)
        case 'max':
            return Math.max(...values)
        case 'sum':
            return values.reduce((a, b) => a + b, 0)
        case 'delta':
            return values[values.length - 1] - values[0]
    }
}

/** One row of a flattened series: the label columns plus one column per reducer.
 * The table panel, the bar gauge, and the time-series legend table all read this shape. */
export interface MetricsSeriesRow {
    /** The series' label set, e.g. { service: "api", pod: "api-1" }. Empty for an ungrouped series. */
    labels: Record<string, string>
    /** The series' metric name, used as the row title for ungrouped single-series results. */
    metricName?: string
    /** The reduced value per reducer, keyed by reducer name. `null` means no data. */
    values: Record<MetricsReducer, number | null>
    /** The raw series, kept so a row can link back to its points (sparkline, drill-down). */
    series: MetricsQuerySeries
}

export function flattenSeriesRows(series: MetricsQuerySeries[], reducers: MetricsReducer[]): MetricsSeriesRow[] {
    return series.map((s) => ({
        labels: s.labels,
        metricName: s.metricName ?? undefined,
        values: Object.fromEntries(reducers.map((r) => [r, reduceSeries(s.points, r)])) as Record<
            MetricsReducer,
            number | null
        >,
        series: s,
    }))
}
