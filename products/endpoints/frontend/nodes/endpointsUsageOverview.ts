import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber, humanizeBytes } from 'lib/utils/numbers'

import { EndpointsUsageOverviewItem } from '~/queries/schema/schema-general'

export type MetricKey =
    | 'total_requests'
    | 'total_bytes_read'
    | 'total_cpu_seconds'
    | 'avg_query_duration_ms'
    | 'p95_query_duration_ms'
    | 'error_rate'
    | 'materialized_requests'
    | 'inline_requests'

export const LABEL_FROM_KEY: Record<MetricKey, string> = {
    total_requests: 'Total executions',
    total_bytes_read: 'Total bytes read',
    total_cpu_seconds: 'CPU seconds',
    avg_query_duration_ms: 'Avg duration',
    p95_query_duration_ms: 'P95 duration',
    error_rate: 'Error rate',
    materialized_requests: 'Materialized executions',
    inline_requests: 'Direct executions',
}

export const PRIMARY_METRICS: MetricKey[] = ['total_requests', 'total_bytes_read', 'total_cpu_seconds']
export const SECONDARY_METRICS: MetricKey[] = [
    'avg_query_duration_ms',
    'p95_query_duration_ms',
    'error_rate',
    'materialized_requests',
    'inline_requests',
]

/**
 * Which way a change is good. `null` is a volume the page cannot judge, so its change stays neutral.
 * A rising error rate or latency is bad news, which a plain "up is green" rule gets backwards.
 */
export const GOOD_DIRECTION: Record<MetricKey, 'up' | 'down' | null> = {
    total_requests: null,
    total_bytes_read: null,
    total_cpu_seconds: null,
    avg_query_duration_ms: 'down',
    p95_query_duration_ms: 'down',
    error_rate: 'down',
    materialized_requests: null,
    inline_requests: null,
}

export const formatItem = (item: EndpointsUsageOverviewItem): string => {
    const value = item.value

    if (value === null || value === undefined) {
        return '0'
    }

    switch (item.key) {
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

export function changeVariant(key: MetricKey, changePct: number): 'default' | 'success' | 'destructive' {
    const goodDirection = GOOD_DIRECTION[key]
    if (changePct === 0 || goodDirection === null) {
        return 'default'
    }
    return changePct > 0 === (goodDirection === 'up') ? 'success' : 'destructive'
}
