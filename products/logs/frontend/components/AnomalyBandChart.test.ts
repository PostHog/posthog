import type { LogsSeriesBandBucketApi } from 'products/logs/frontend/generated/api.schemas'

import { buildBandChartData, clickableBucketTimes } from './AnomalyBandChart'

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

    describe('clickableBucketTimes', () => {
        // Every charted bucket is a complete interval. Without the appended end, a click on the
        // newest one would open a range running to "now", covering the current uncharted interval
        // on top of the one that was clicked.
        it('closes the last bucket at its own end', () => {
            expect(clickableBucketTimes(['2026-08-06T10:00:00Z', '2026-08-06T11:00:00Z'])).toEqual([
                '2026-08-06T10:00:00Z',
                '2026-08-06T11:00:00Z',
                '2026-08-06T12:00:00.000Z',
            ])
        })

        it('leaves a single bucket alone, having no width to measure', () => {
            expect(clickableBucketTimes(['2026-08-06T10:00:00Z'])).toEqual(['2026-08-06T10:00:00Z'])
        })
    })
})
