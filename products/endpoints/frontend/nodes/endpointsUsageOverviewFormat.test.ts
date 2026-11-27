import { EndpointsUsageOverviewItemKey } from '~/queries/schema/schema-general'

import { EndpointsUsageChangeTone, endpointsUsageChangeTone } from './endpointsUsageOverviewFormat'

describe('endpointsUsageOverviewFormat', () => {
    it.each<[EndpointsUsageOverviewItemKey, number, EndpointsUsageChangeTone]>([
        ['error_rate', 12, 'bad'],
        ['error_rate', -12, 'good'],
        ['p95_query_duration_ms', 5, 'bad'],
        ['avg_query_duration_ms', -5, 'good'],
        ['total_requests', 40, 'neutral'],
        ['total_bytes_read', -40, 'neutral'],
        ['total_cpu_seconds', 9, 'neutral'],
        ['error_rate', 0, 'neutral'],
    ])('%s changing by %d%% reads as %s', (key, changePct, expected) => {
        expect(endpointsUsageChangeTone(key, changePct)).toBe(expected)
    })
})
