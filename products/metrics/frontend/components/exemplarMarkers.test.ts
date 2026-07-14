import type { _MetricEventSampleApi } from 'products/metrics/frontend/generated/api.schemas'

import { exemplarMarkersFromSamples } from './exemplarMarkers'

const BUCKETS = ['2026-07-14T10:00:00Z', '2026-07-14T10:01:00Z', '2026-07-14T10:02:00Z', '2026-07-14T10:03:00Z']

function sample(overrides: Partial<_MetricEventSampleApi>): _MetricEventSampleApi {
    return {
        timestamp: '2026-07-14T10:00:10Z',
        metric_name: 'queue.depth',
        metric_type: 'gauge',
        value: 7,
        count: 1,
        unit: '',
        aggregation_temporality: 'delta',
        is_monotonic: false,
        service_name: 'svc',
        trace_id: 'abc123def456',
        span_id: 'span1',
        attributes: {},
        resource_attributes: {},
        ...overrides,
    }
}

describe('exemplarMarkersFromSamples', () => {
    it('maps trace-linked samples to their nearest chart bucket', () => {
        const markers = exemplarMarkersFromSamples(
            [
                sample({ timestamp: '2026-07-14T10:00:10Z', value: 7 }),
                // 10:02:40 is nearer to the 10:03 bucket than the 10:02 one.
                sample({ timestamp: '2026-07-14T10:02:40Z', value: 12, trace_id: 'ffff0000' }),
            ],
            BUCKETS
        )

        expect(markers).toEqual([
            expect.objectContaining({ index: 0, value: 7, traceId: 'abc123def456' }),
            expect.objectContaining({ index: 3, value: 12, traceId: 'ffff0000' }),
        ])
    })

    it('drops samples without a trace and dedupes to the newest sample per bucket', () => {
        const markers = exemplarMarkersFromSamples(
            [
                // Endpoint returns newest-first; both land in bucket 1 and the newest must win.
                sample({ timestamp: '2026-07-14T10:01:20Z', value: 99, trace_id: 'newest' }),
                sample({ timestamp: '2026-07-14T10:01:05Z', value: 1, trace_id: 'older' }),
                sample({ timestamp: '2026-07-14T10:01:10Z', value: 5, trace_id: '' }),
            ],
            BUCKETS
        )

        expect(markers).toHaveLength(1)
        expect(markers[0]).toEqual(expect.objectContaining({ index: 1, traceId: 'newest', value: 99 }))
    })

    it('returns nothing without buckets or samples', () => {
        expect(exemplarMarkersFromSamples([], BUCKETS)).toEqual([])
        expect(exemplarMarkersFromSamples([sample({})], [])).toEqual([])
    })
})
