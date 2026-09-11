import type { MetricsReducer } from '~/queries/schema/schema-general'

/** One bucket. `value` is `null` for a non-representable aggregate (a gap). The schema's
 * `MetricsQueryPoint` declares `value: number` but the backend sends null, so this shape
 * matches what both the schema series and the viewer's API series actually carry. */
export interface ReduciblePoint {
    time: string
    value: number | null
}

/** The shape `flattenSeriesRows` needs. A structural subset of both the schema series and
 * the viewer's `MetricsChartSeries`, so either flows in. */
export interface ReducibleSeries {
    labels: Record<string, string>
    points: ReduciblePoint[]
    metricName?: string | null
    unit?: string | null
}

/** The reducers a caller may ask for. `reduceSeries` returns `null` when a series has no
 * non-null point, so a panel can show "No data" instead of a misleading 0. */
export function reduceSeries(points: ReduciblePoint[], reducer: MetricsReducer): number | null {
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
    series: ReducibleSeries
}

export function flattenSeriesRows(series: ReducibleSeries[], reducers: MetricsReducer[]): MetricsSeriesRow[] {
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
