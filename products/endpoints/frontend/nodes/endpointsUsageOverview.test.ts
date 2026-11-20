import { type MetricKey, changeVariant } from './endpointsUsageOverview'

describe('changeVariant', () => {
    it.each<[MetricKey, number, 'default' | 'success' | 'destructive']>([
        ['error_rate', 12, 'destructive'],
        ['error_rate', -12, 'success'],
        ['p95_query_duration_ms', 5, 'destructive'],
        ['avg_query_duration_ms', -5, 'success'],
        ['total_requests', 40, 'default'],
        ['total_bytes_read', -40, 'default'],
        ['error_rate', 0, 'default'],
    ])('%s changing by %d%% is %s', (key, changePct, expected) => {
        expect(changeVariant(key, changePct)).toBe(expected)
    })
})
