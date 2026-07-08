import type { _MetricSeriesApi } from 'products/metrics/frontend/generated/api.schemas'

// PostHog defines data-color-1..15 in vars.scss; cycle through them so each series gets a distinct line.
const SERIES_COLOR_COUNT = 15

export const seriesColor = (index: number): string => `data-color-${(index % SERIES_COLOR_COUNT) + 1}`

// Human-readable series name from its label map (e.g. "service.name=checkout, env=prod"),
// falling back to the metric name then a provided default for ungrouped/unlabelled series.
export const formatSeriesName = (series: _MetricSeriesApi, fallback: string, withClausePrefix = false): string => {
    const entries = Object.entries(series.labels ?? {})
    const base =
        entries.length > 0
            ? entries.map(([key, value]) => `${key}=${value}`).join(', ')
            : (series.metric_name ?? fallback)
    if (withClausePrefix && series.clause && series.clause !== 'formula') {
        return `${series.clause}. ${base}`
    }
    return base
}
