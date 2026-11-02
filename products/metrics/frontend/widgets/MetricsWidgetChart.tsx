import type { MetricsHistogramQueryResponse, MetricsQuery } from '~/queries/schema/schema-general'

import { metricsQueryFallbackName, seriesFromMetricsResponse } from '../nodes/metricsResponseSeries'
import { HeatmapPanel } from '../panels/HeatmapPanel'
import { MetricsPanel } from '../panels/MetricsPanel'
import { isMetricsHeatmapQuery } from './metricsHeatmapQuery'
import { MetricsWidgetMessage } from './MetricsWidgetMessage'

function isHistogramResponse(response: unknown): response is MetricsHistogramQueryResponse {
    return typeof response === 'object' && response !== null && Array.isArray((response as { times?: unknown }).times)
}

/** Draws a metric widget's query result: a heatmap grid for the heatmap display, otherwise the matching panel. */
export function MetricsWidgetChart({ query, response }: { query: MetricsQuery; response: unknown }): JSX.Element {
    if (isMetricsHeatmapQuery(query) && isHistogramResponse(response)) {
        if (response.times.length === 0) {
            return <MetricsWidgetMessage>No data for this metric in the selected range.</MetricsWidgetMessage>
        }
        return <HeatmapPanel response={response} unit={query.display?.unit} />
    }

    const series = seriesFromMetricsResponse(response)
    if (!series.some((s) => s.points.length > 0)) {
        return <MetricsWidgetMessage>No data for this metric in the selected range.</MetricsWidgetMessage>
    }
    return (
        <MetricsPanel
            series={series}
            fallbackName={metricsQueryFallbackName(query)}
            display={query.display}
            query={query}
        />
    )
}
