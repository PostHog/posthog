import type { _MetricSeriesApi } from 'products/metrics/frontend/generated/api.schemas'

/** Source-agnostic series shape for the metrics chart: the REST viewer (`_MetricSeriesApi`) and the
 * `MetricsQuery` schema node (`MetricsQuerySeries`) both map onto it. */
export interface MetricsChartSeries {
    labels: Record<string, string>
    points: { time: string; value: number | null }[]
    metricName?: string | null
    /** Alias of the query clause that produced this series (`formula` for a formula result). */
    clause?: string | null
}

// PostHog defines data-color-1..15 in vars.scss; cycle through them so each series gets a distinct line.
const SERIES_COLOR_COUNT = 15

export const seriesColor = (index: number): string => `data-color-${(index % SERIES_COLOR_COUNT) + 1}`

type NamableSeries = Pick<_MetricSeriesApi, 'labels' | 'metric_name'> & { clause?: string | null }

// Human-readable series name from its label map (e.g. "service.name=checkout, env=prod"),
// falling back to the metric name then a provided default for ungrouped/unlabelled series.
const formatSeriesName = (series: NamableSeries, fallback: string, showClause: boolean): string => {
    const prefix = showClause && series.clause ? `${series.clause} · ` : ''
    const entries = Object.entries(series.labels ?? {})
    if (entries.length > 0) {
        return prefix + entries.map(([key, value]) => `${key}=${value}`).join(', ')
    }
    return prefix + (series.metric_name ?? fallback)
}

/** Display names for a whole chart's series, index-aligned with the input. The clause
 * alias prefixes each name (e.g. "a · env=prod") only when the list plots more than
 * one clause — that is the case where two ungrouped series would otherwise collide,
 * and deciding here keeps every consumer (legend, aggregates table) in agreement. */
export const formatSeriesNames = (seriesList: NamableSeries[], fallback: string): string[] => {
    const showClause = new Set(seriesList.map((s) => s.clause).filter(Boolean)).size > 1
    return seriesList.map((series) => formatSeriesName(series, fallback, showClause))
}
