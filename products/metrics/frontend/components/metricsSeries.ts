import type { _MetricSeriesApi } from 'products/metrics/frontend/generated/api.schemas'

/** Source-agnostic series shape for the metrics chart: the REST viewer (`_MetricSeriesApi`) and the
 * `MetricsQuery` schema node (`MetricsQuerySeries`) both map onto it. */
export interface MetricsChartSeries {
    labels: Record<string, string>
    points: { time: string; value: number | null }[]
    metricName?: string | null
    /** Alias of the query clause that produced this series (`formula` for a formula result). */
    clause?: string | null
    /** UCUM unit of the values, as the query resolves it, e.g. "By", "ms", "1/s". Absent when the values have no unit. */
    unit?: string | null
}

// PostHog defines data-color-1..15 in vars.scss; cycle through them so each series gets a distinct line.
const SERIES_COLOR_COUNT = 15

export const seriesColor = (index: number): string => `data-color-${(index % SERIES_COLOR_COUNT) + 1}`

type NamableSeries = Pick<_MetricSeriesApi, 'labels' | 'metric_name'> & { clause?: string | null }

export type SeriesLabel = [key: string, value: string]

/** Clause alias prefix ("a · ") per series. Empty unless the list plots more than one clause. */
export const seriesNamePrefixes = (seriesList: NamableSeries[]): string[] => {
    const showClause = new Set(seriesList.map((s) => s.clause).filter(Boolean)).size > 1
    return seriesList.map((series) => (showClause && series.clause ? `${series.clause} · ` : ''))
}

// Human-readable series name from its label map (e.g. "service.name=checkout, env=prod"),
// falling back to the metric name then a provided default for ungrouped/unlabelled series.
const formatSeriesName = (series: NamableSeries, fallback: string, prefix: string): string => {
    const entries = Object.entries(series.labels ?? {})
    if (entries.length > 0) {
        return prefix + entries.map(([key, value]) => `${key}=${value}`).join(', ')
    }
    return prefix + (series.metric_name ?? fallback)
}

/** Display names for a whole chart's series, index-aligned with the input. The clause
 * alias prefixes each name (e.g. "a · env=prod") only when the list plots more than
 * one clause — that is the case where two ungrouped series would otherwise collide,
 * and deciding here keeps every consumer (legend, series table) in agreement. */
export const formatSeriesNames = (seriesList: NamableSeries[], fallback: string): string[] => {
    const prefixes = seriesNamePrefixes(seriesList)
    return seriesList.map((series, index) => formatSeriesName(series, fallback, prefixes[index]))
}

/** Per series, the labels that differ between series. Labels with the same value on every series
 * (e.g. Kubernetes app labels) are dropped. A single series keeps all its labels. */
export const distinctSeriesLabels = (seriesList: Pick<NamableSeries, 'labels'>[]): SeriesLabel[][] => {
    const [first, ...rest] = seriesList
    const sharedKeys = new Set(
        rest.length > 0
            ? Object.entries(first.labels ?? {})
                  .filter(([key, value]) => rest.every((series) => series.labels?.[key] === value))
                  .map(([key]) => key)
            : []
    )
    return seriesList.map((series) => Object.entries(series.labels ?? {}).filter(([key]) => !sharedKeys.has(key)))
}
