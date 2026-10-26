import type { MetricsQuery } from '~/queries/schema/schema-general'

import { MetricsQueryEditorSection } from '../components/MetricsQueryEditorSection'
import { MetricsHistogramQueryNode } from '../nodes/MetricsHistogramQueryNode'
import { MetricsQueryNode } from '../nodes/MetricsQueryNode'
import { isMetricsHeatmapQuery, metricsHeatmapIneligibleReason, metricsHistogramQueryFor } from './metricsHeatmapQuery'
import { MetricsWidgetMessage } from './MetricsWidgetMessage'

/** Edits a metric widget's query with the metrics builder, PromQL or SQL, above a live preview of the tile. */
export function MetricsWidgetQueryEditor({
    query,
    setQuery,
}: {
    query: MetricsQuery
    setQuery: (query: MetricsQuery) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-3 min-w-0">
            <MetricsQueryEditorSection query={query} setQuery={setQuery} surface="widget" />
            <div className="relative flex h-[320px] min-w-0 border rounded p-3" data-attr="metrics-widget-preview">
                <MetricsWidgetQueryPreview query={query} />
            </div>
        </div>
    )
}

function MetricsWidgetQueryPreview({ query }: { query: MetricsQuery }): JSX.Element {
    if (!isMetricsHeatmapQuery(query)) {
        return <MetricsQueryNode query={query} context={{}} />
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
