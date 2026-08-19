import type { _MetricSeriesApi } from 'products/metrics/frontend/generated/api.schemas'

/** Source-agnostic series shape for the metrics chart: the REST viewer (`_MetricSeriesApi`) and the
 * `MetricsQuery` schema node (`MetricsQuerySeries`) both map onto it. */
export interface MetricsChartSeries {
    labels: Record<string, string>
    points: { time: string; value: number | null }[]
    metricName?: string | null
}

// PostHog defines data-color-1..15 in vars.scss; cycle through them so each series gets a distinct line.
const SERIES_COLOR_COUNT = 15

export const seriesColor = (index: number): string => `data-color-${(index % SERIES_COLOR_COUNT) + 1}`

// Human-readable series name from its label map (e.g. "service.name=checkout, env=prod"),
// falling back to the metric name then a provided default for ungrouped/unlabelled series.
export const formatSeriesName = (
    series: Pick<_MetricSeriesApi, 'labels' | 'metric_name'>,
    fallback: string
): string => {
    const entries = Object.entries(series.labels ?? {})
    if (entries.length > 0) {
        return entries.map(([key, value]) => `${key}=${value}`).join(', ')
    }
    return series.metric_name ?? fallback
}
