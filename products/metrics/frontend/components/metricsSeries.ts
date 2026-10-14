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

export interface SeriesLabelSplit {
    /** Labels that every series has with the same value. */
    shared: SeriesLabel[]
    /** Per series, index-aligned with the input: the labels that tell it apart. */
    distinct: SeriesLabel[][]
}

/** The clause alias prefix ("a · ") of each series, index-aligned with the input. It is empty unless
 * the list plots more than one clause, which is when two ungrouped series would otherwise collide. */
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

/** Splits the labels into the ones every series has with the same value (often deployment
 * labels such as the Kubernetes app name) and, per series, the ones that tell it apart.
 * All labels of a single series count as shared. */
export const splitSharedSeriesLabels = (seriesList: Pick<NamableSeries, 'labels'>[]): SeriesLabelSplit => {
    const [first, ...rest] = seriesList
    const shared: SeriesLabel[] = Object.entries(first?.labels ?? {}).filter(([key, value]) =>
        rest.every((series) => series.labels?.[key] === value)
    )
    const sharedKeys = new Set(shared.map(([key]) => key))
    return {
        shared,
        distinct: seriesList.map((series) =>
            Object.entries(series.labels ?? {}).filter(([key]) => !sharedKeys.has(key))
        ),
    }
}
