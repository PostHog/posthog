import type { MetricsQuery } from '~/queries/schema/schema-general'

import { MetricsHistogramQueryNode } from '../nodes/MetricsHistogramQueryNode'
import { MetricsQueryNode } from '../nodes/MetricsQueryNode'
import { isMetricsHeatmapQuery, metricsHeatmapIneligibleReason, metricsHistogramQueryFor } from './metricsHeatmapQuery'
import { MetricsWidgetMessage } from './MetricsWidgetMessage'

/** Runs a metric widget's query as the tile would and draws it, the heatmap through its histogram query. */
export function MetricsWidgetQueryPreview({ query, dataKey }: { query: MetricsQuery; dataKey: string }): JSX.Element {
    if (!isMetricsHeatmapQuery(query)) {
        return <MetricsQueryNode query={query} context={{}} dataKey={dataKey} />
    }
    if (!query.clauses.length) {
        return <MetricsWidgetMessage>Pick a histogram metric to see its heatmap.</MetricsWidgetMessage>
    }
    const histogramQuery = metricsHistogramQueryFor(query)
    if (!histogramQuery) {
        return <MetricsWidgetMessage>{metricsHeatmapIneligibleReason(query) ?? ''}</MetricsWidgetMessage>
    }
    return <MetricsHistogramQueryNode query={histogramQuery} context={{}} />
}
