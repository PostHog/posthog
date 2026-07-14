import type { _MetricEventSampleApi } from 'products/metrics/frontend/generated/api.schemas'

import { exemplarMarkersFromSamples } from './exemplarMarkers'

const SERIES = [
    {
        labels: {},
        points: [
            { time: '2026-07-14T10:00:00Z', value: 10 },
            { time: '2026-07-14T10:01:00Z', value: 20 },
            { time: '2026-07-14T10:02:00Z', value: 30 },
            { time: '2026-07-14T10:03:00Z', value: 40 },
        ],
    },
]

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

const NO_OPTS = { groupByKeys: [], filters: [] }

describe('exemplarMarkersFromSamples', () => {
    it('floors samples into their containing bucket and pins the dot to the series value', () => {
        const markers = exemplarMarkersFromSamples(
            [
                sample({ timestamp: '2026-07-14T10:00:10Z' }),
                // 10:02:40 belongs to the 10:02 bucket it aggregated into, not the nearer 10:03.
                sample({ timestamp: '2026-07-14T10:02:40Z', trace_id: 'ffff0000' }),
            ],
            SERIES,
            NO_OPTS
        )

        expect(markers).toEqual([
            expect.objectContaining({ index: 0, value: 10, traceId: 'abc123def456' }),
            expect.objectContaining({ index: 2, value: 30, traceId: 'ffff0000' }),
        ])
    })

    it('drops samples outside the bucket window instead of clamping them to the edges', () => {
        const markers = exemplarMarkersFromSamples(
            [
                sample({ timestamp: '2026-07-14T09:59:00Z', trace_id: 'before' }),
                sample({ timestamp: '2026-07-14T10:05:30Z', trace_id: 'after' }),
                sample({ timestamp: '2026-07-14T10:03:30Z', trace_id: 'in-last-bucket' }),
            ],
            SERIES,
            NO_OPTS
        )

        expect(markers).toEqual([expect.objectContaining({ index: 3, traceId: 'in-last-bucket' })])
    })

    it('drops non-traced samples and dedupes to the newest per bucket', () => {
        // Older sample first, so keep-newest can't be faked by keep-first-seen:
        // the API does not promise chronological order.
        const markers = exemplarMarkersFromSamples(
            [
                sample({ timestamp: '2026-07-14T10:01:05Z', trace_id: 'older' }),
                sample({ timestamp: '2026-07-14T10:01:20Z', trace_id: 'newest' }),
                sample({ timestamp: '2026-07-14T10:01:10Z', trace_id: '' }),
            ],
            SERIES,
            NO_OPTS
        )

        expect(markers).toHaveLength(1)
        expect(markers[0]).toEqual(expect.objectContaining({ index: 1, traceId: 'newest', value: 20 }))
    })

    it('applies the chart filters client-side, with negative operators matching missing keys', () => {
        const samples = [
            sample({ attributes: { env: 'prod' }, trace_id: 'keep-eq' }),
            sample({ attributes: { env: 'dev' }, trace_id: 'drop-eq', timestamp: '2026-07-14T10:01:10Z' }),
        ]

        expect(
            exemplarMarkersFromSamples(samples, SERIES, {
                groupByKeys: [],
                filters: [{ key: 'env', op: 'eq', value: 'prod' }],
            }).map((m) => m.traceId)
        ).toEqual(['keep-eq'])

        // neq matches rows lacking the key entirely, mirroring Prometheus negative matchers.
        expect(
            exemplarMarkersFromSamples([sample({ attributes: {}, trace_id: 'no-key' })], SERIES, {
                groupByKeys: [],
                filters: [{ key: 'env', op: 'neq', value: 'prod' }],
            }).map((m) => m.traceId)
        ).toEqual(['no-key'])
    })

    it('pins grouped samples to their matching series and drops samples with no series', () => {
        const grouped = [
            { labels: { container: 'a' }, points: SERIES[0].points },
            {
                labels: { container: 'b' },
                points: SERIES[0].points.map((point) => ({ ...point, value: (point.value ?? 0) * 10 })),
            },
        ]
        const markers = exemplarMarkersFromSamples(
            [
                sample({ attributes: { container: 'b' }, trace_id: 'goes-to-b' }),
                sample({ attributes: { container: 'zz' }, trace_id: 'orphan', timestamp: '2026-07-14T10:01:10Z' }),
            ],
            grouped,
            { groupByKeys: ['container'], filters: [] }
        )

        expect(markers).toEqual([expect.objectContaining({ index: 0, value: 100, traceId: 'goes-to-b' })])
    })

    it('skips buckets where the matched series has a gap', () => {
        const gappy = [{ labels: {}, points: SERIES[0].points.map((p, i) => (i === 0 ? { ...p, value: null } : p)) }]
        expect(exemplarMarkersFromSamples([sample({})], gappy, NO_OPTS)).toEqual([])
    })

    it('returns nothing without buckets or samples', () => {
        expect(exemplarMarkersFromSamples([], SERIES, NO_OPTS)).toEqual([])
        expect(exemplarMarkersFromSamples([sample({})], [], NO_OPTS)).toEqual([])
    })
})
