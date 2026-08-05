import type { IndexedTrendResult } from 'scenes/trends/types'

import { hasTrendsChartData } from './hasTrendsChartData'

function makeResult(overrides: Partial<IndexedTrendResult> = {}): IndexedTrendResult {
    return {
        action: null,
        count: 0,
        data: [],
        days: [],
        labels: [],
        label: '',
        aggregated_value: 0,
        seriesIndex: 0,
        id: 0,
        ...overrides,
    } as IndexedTrendResult
}

describe('hasTrendsChartData', () => {
    it('returns false for an empty or undefined result set', () => {
        expect(hasTrendsChartData(undefined)).toBe(false)
        expect(hasTrendsChartData([])).toBe(false)
    })

    it('returns false when every series is empty', () => {
        const results = [makeResult({ data: [0, 0], count: 0 }), makeResult({ data: [0, 0], count: 0 })]
        expect(hasTrendsChartData(results)).toBe(false)
    })

    it('returns true when a later series has data, even if the first series is empty', () => {
        const results = [makeResult({ data: undefined, count: 0 }), makeResult({ data: [1, 2, 3], count: 6 })]
        expect(hasTrendsChartData(results)).toBe(true)
    })

    it('returns true for a non-zero aggregated value even without a data array', () => {
        const results = [makeResult({ data: undefined, count: 0, aggregated_value: 42 })]
        expect(hasTrendsChartData(results)).toBe(true)
    })

    it('ignores a non-finite aggregated value', () => {
        const results = [makeResult({ data: undefined, count: 0, aggregated_value: NaN })]
        expect(hasTrendsChartData(results)).toBe(false)
    })
})
