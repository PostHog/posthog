import { MetricsQuerySeries } from '~/queries/schema/schema-general'

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
