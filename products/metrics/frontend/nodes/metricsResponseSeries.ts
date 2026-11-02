import { truncate } from 'lib/utils/strings'

import { MetricsQuery, MetricsQuerySeries } from '~/queries/schema/schema-general'

/**
 * Dashboard tiles hand dataNodeLogic the cached insight object, whose data sits
 * under `result` (singular); live query responses carry `results`. Accept both
 * so a metrics tile renders from cache instead of blank.
 */
export function seriesFromMetricsResponse(response: unknown): MetricsQuerySeries[] {
    if (!response || typeof response !== 'object') {
        return []
    }
    const { results, result } = response as { results?: unknown; result?: unknown }
    if (Array.isArray(results)) {
        return results as MetricsQuerySeries[]
    }
    if (Array.isArray(result)) {
        return result as MetricsQuerySeries[]
    }
    return []
}

/** The name for a series without labels. A formula query returns only the formula result (metricName is null on
 * it), so the formula text itself is the honest name for an unlabelled series. */
export function metricsQueryFallbackName(query: MetricsQuery): string {
    return (
        query.formula ??
        query.clauses[0]?.metricName ??
        (query.language === 'promql' && query.promql ? truncate(query.promql, 80) : 'metric')
    )
}
