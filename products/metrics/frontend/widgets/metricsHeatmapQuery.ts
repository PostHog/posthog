import { MetricsHistogramQuery, MetricsOtelType, MetricsQuery, NodeKind } from '~/queries/schema/schema-general'

import { queryLanguage } from '../queryLanguages/convert'

const HISTOGRAM_METRIC_TYPES: readonly MetricsOtelType[] = ['histogram', 'exponential_histogram', 'summary']

/** Why a query with the heatmap display can't draw one, or null when it can. Mirrors the backend's
 * `metrics_histogram_query_for`, so the editor preview and the dashboard tile agree. */
export function metricsHeatmapIneligibleReason(query: MetricsQuery): string | null {
    if (queryLanguage(query) !== 'builder') {
        return "A heatmap needs a builder query. PromQL and SQL can't draw one."
    }
    if (query.clauses.length !== 1 || query.formula) {
        return 'A heatmap needs exactly one metric and no formula.'
    }
    const [clause] = query.clauses
    if (clause.groupBy?.length) {
        return "A heatmap can't group by attributes. Remove the group-by."
    }
    if (!clause.metricType || !HISTOGRAM_METRIC_TYPES.includes(clause.metricType)) {
        return 'A heatmap needs a histogram metric.'
    }
    return null
}

/** The histogram query that draws a metrics query with the heatmap display, or null when it can't. */
export function metricsHistogramQueryFor(query: MetricsQuery): MetricsHistogramQuery | null {
    if (metricsHeatmapIneligibleReason(query) !== null) {
        return null
    }
    const [clause] = query.clauses
    return {
        kind: NodeKind.MetricsHistogramQuery,
        metricName: clause.metricName.trim(),
        metricType: clause.metricType,
        ...(clause.filters?.length ? { filters: clause.filters } : {}),
        ...(query.dateRange ? { dateRange: query.dateRange } : {}),
        ...(query.interval ? { interval: query.interval } : {}),
    }
}

export function isMetricsHeatmapQuery(query: MetricsQuery): boolean {
    return query.display?.type === 'heatmap'
}
