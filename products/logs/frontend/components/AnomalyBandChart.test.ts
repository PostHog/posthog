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
    it('keeps unscored band values as null instead of coercing to zero', () => {
        // A null band coerced to 0 would render every unscored region as a
        // drop to zero, which is exactly the misreading the chart must avoid.
        const data = buildBandChartData([
            bucket({}),
            bucket({ time: '2026-08-06T10:05:00Z', expected: null, lower: null, upper: null, stage: null }),
        ])
        expect(data.lower).toEqual([4, null])
        expect(data.upper).toEqual([21, null])
        expect(data.observed).toEqual([12, 12])
    })

    it('carries verdicts positionally so anomalous points can be highlighted', () => {
        const data = buildBandChartData([
            bucket({}),
            bucket({ time: '2026-08-06T10:05:00Z', observed: 47, verdict: 'spike' }),
        ])
        expect(data.verdicts).toEqual([null, 'spike'])
    })

    it('switches label format when the window spans multiple days', () => {
        const sameDay = buildBandChartData([bucket({}), bucket({ time: '2026-08-06T10:05:00Z' })])
        expect(sameDay.labels[0]).toMatch(/^\d{2}:\d{2}$/)

        const multiDay = buildBandChartData([bucket({}), bucket({ time: '2026-08-07T10:00:00Z' })])
        expect(multiDay.labels[0]).toMatch(/^[A-Z][a-z]{2} \d{1,2} \d{2}:\d{2}$/)
    })
})
