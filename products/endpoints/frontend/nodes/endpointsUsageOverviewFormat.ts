import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber, humanizeBytes } from 'lib/utils/numbers'

import { EndpointsUsageOverviewItemKey } from '~/queries/schema/schema-general'

export const ENDPOINTS_USAGE_OVERVIEW_LABELS: Record<EndpointsUsageOverviewItemKey, string> = {
    total_requests: 'Total executions',
    materialized_requests: 'Materialized executions',
    inline_requests: 'Direct executions',
    error_rate: 'Error rate',
    avg_query_duration_ms: 'Avg duration',
    p95_query_duration_ms: 'P95 duration',
    total_bytes_read: 'Total bytes read',
    total_cpu_seconds: 'CPU seconds',
}

/** The tile order of the overview: executions first, then how they performed, then what they cost. */
export const ENDPOINTS_USAGE_OVERVIEW_KEYS = Object.keys(
    ENDPOINTS_USAGE_OVERVIEW_LABELS
) as EndpointsUsageOverviewItemKey[]

/**
 * Whether a rise in the metric is good news, which decides the color of its change pill. More executions is good.
 * Slower, failing or costlier executions are not.
 */
export const ENDPOINTS_USAGE_OVERVIEW_GOOD_DIRECTION: Record<EndpointsUsageOverviewItemKey, 'up' | 'down'> = {
    total_requests: 'up',
    materialized_requests: 'up',
    inline_requests: 'up',
    error_rate: 'down',
    avg_query_duration_ms: 'down',
    p95_query_duration_ms: 'down',
    total_bytes_read: 'down',
    total_cpu_seconds: 'down',
}

export function formatEndpointsUsageOverviewValue(
    key: EndpointsUsageOverviewItemKey,
    value: number | null | undefined
): string {
    if (value === null || value === undefined) {
        return '0'
    }

    switch (key) {
        case 'total_requests':
        case 'materialized_requests':
        case 'inline_requests':
            return humanFriendlyNumber(value)

        case 'total_bytes_read':
            return humanizeBytes(value)

        case 'total_cpu_seconds':
            return humanFriendlyDuration(value)

        case 'avg_query_duration_ms':
        case 'p95_query_duration_ms':
            // Convert ms to seconds for humanFriendlyDuration
            return humanFriendlyDuration(value / 1000)

        case 'error_rate':
            return `${(value * 100).toFixed(2)}%`

        default:
            return humanFriendlyNumber(value)
    }
}
