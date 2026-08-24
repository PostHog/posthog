import type { LogsSeriesBandBucketApi } from 'products/logs/frontend/generated/api.schemas'

import { bucketRange, buildBandChartData } from './AnomalyBandChart'

function bucket(overrides: Partial<LogsSeriesBandBucketApi>): LogsSeriesBandBucketApi {
    return {
        time: '2026-08-06T10:00:00Z',
        observed: 12,
        lower: 4,
        upper: 21,
        ...overrides,
    }
}

describe('AnomalyBandChart', () => {
    describe('buildBandChartData', () => {
        it('leaves unbanded values non-finite instead of coercing to zero', () => {
            // A null band coerced to 0 would render every unbanded region as a
            // drop to zero, which is exactly the misreading the chart must avoid.
            // The band breaks at a non-finite value, which is how the gap is drawn.
            const data = buildBandChartData([
                bucket({}),
                bucket({ time: '2026-08-06T11:00:00Z', lower: null, upper: null }),
            ])
            expect(data.lower).toEqual([4, NaN])
            expect(data.upper).toEqual([21, NaN])
            expect(data.observed).toEqual([12, 12])
        })

        it('marks points outside the band, and never marks unbanded points', () => {
            const data = buildBandChartData([
                bucket({}),
                bucket({ time: '2026-08-06T11:00:00Z', observed: 47 }),
                bucket({ time: '2026-08-06T12:00:00Z', observed: 1 }),
                bucket({ time: '2026-08-06T13:00:00Z', observed: 47, lower: null, upper: null }),
            ])
            expect(data.outOfBand).toEqual([null, 'above', 'below', null])
        })

        it('labels buckets with their raw times so the time axis can format them', () => {
            // Pre-formatted display strings would be printed verbatim by the time axis, which
            // costs the interval-aware ticks and the tooltip's date header.
            const data = buildBandChartData([bucket({}), bucket({ time: '2026-08-06T11:00:00Z' })])
            expect(data.labels).toEqual(['2026-08-06T10:00:00Z', '2026-08-06T11:00:00Z'])
        })
    })

    describe('bucketRange', () => {
        const buckets = ['10:00', '11:00', '12:00', '13:00'].map((time) => bucket({ time: `2026-08-06T${time}:00Z` }))

        // Every index names a bucket start. A range ending at the last bucket's start would link
        // to everything except the bucket the user actually picked, and a single-bucket click
        // would resolve to an empty window.
        it.each([
            { name: 'a span of buckets', start: 0, end: 2, from: '10:00:00Z', to: '13:00:00.000Z' },
            { name: 'a click on one bucket', start: 1, end: 1, from: '11:00:00Z', to: '12:00:00.000Z' },
            { name: 'a reversed span', start: 2, end: 0, from: '10:00:00Z', to: '13:00:00.000Z' },
        ])('covers whole buckets for $name', ({ start, end, from, to }) => {
            expect(bucketRange(buckets, start, end)).toEqual({
                dateFrom: `2026-08-06T${from}`,
                dateTo: `2026-08-06T${to}`,
            })
        })

        it('returns null when the bucket width cannot be derived', () => {
            expect(bucketRange([bucket({})], 0, 0)).toBeNull()
        })
    })
})
