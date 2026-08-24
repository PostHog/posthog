import type { LogsAnomalyScanBucketApi } from 'products/logs/frontend/generated/api.schemas'

import { buildBandChartData } from './AnomalyBandChart'

function bucket(overrides: Partial<LogsAnomalyScanBucketApi>): LogsAnomalyScanBucketApi {
    return {
        time: '2026-08-06T10:00:00Z',
        observed: 12,
        expected: 11,
        lower: 4,
        upper: 21,
        stage: 'mature',
        verdict: null,
        ...overrides,
    }
}

describe('buildBandChartData', () => {
    it('leaves unscored band values non-finite instead of coercing to zero', () => {
        // A null band coerced to 0 would render every unscored region as a
        // drop to zero, which is exactly the misreading the chart must avoid.
        // The band breaks at a non-finite value, which is how the gap is drawn.
        const data = buildBandChartData([
            bucket({}),
            bucket({ time: '2026-08-06T10:05:00Z', expected: null, lower: null, upper: null, stage: null }),
        ])
        expect(data.lower).toEqual([4, NaN])
        expect(data.upper).toEqual([21, NaN])
        expect(data.observed).toEqual([12, 12])
    })

    it('carries verdicts positionally so anomalous points can be highlighted', () => {
        const data = buildBandChartData([
            bucket({}),
            bucket({ time: '2026-08-06T10:05:00Z', observed: 47, verdict: 'spike' }),
        ])
        expect(data.verdicts).toEqual([null, 'spike'])
    })

    it('labels buckets with their raw times so the time axis can format them', () => {
        // Pre-formatted display strings would be printed verbatim by the time axis, which
        // costs the interval-aware ticks and the tooltip's date header.
        const data = buildBandChartData([bucket({}), bucket({ time: '2026-08-06T10:05:00Z' })])
        expect(data.labels).toEqual(['2026-08-06T10:00:00Z', '2026-08-06T10:05:00Z'])
    })
})
