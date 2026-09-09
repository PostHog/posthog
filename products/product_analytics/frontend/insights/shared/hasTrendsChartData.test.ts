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
        colorIndex: 0,
        ...overrides,
    }
}

// `TrendResult['data']` is typed as non-nullable `number[]`, but the aggregated-formula path on
// the backend really does send `data: None` over the wire — the `!!result.data` guard in
// `hasTrendsChartData` exists for that case. Cast at the call site (not by widening the shared
// type) to model the real, type-violating payload without loosening `data` for every consumer.
const withMissingData = (overrides: Partial<IndexedTrendResult> = {}): IndexedTrendResult =>
    makeResult({ data: undefined, ...overrides } as Partial<IndexedTrendResult>)

describe('hasTrendsChartData', () => {
    it.each<[string, IndexedTrendResult[] | undefined, boolean]>([
        ['undefined result set', undefined, false],
        ['empty result set', [], false],
        ['every series empty', [makeResult({ data: [0, 0], count: 0 }), makeResult({ data: [0, 0], count: 0 })], false],
        [
            'a later series has data, even if the first series is empty',
            [makeResult({ data: [0, 0, 0], count: 0 }), makeResult({ data: [1, 2, 3], count: 6 })],
            true,
        ],
        [
            'non-zero aggregated value even with a missing data array (aggregated query shape)',
            [withMissingData({ count: 0, aggregated_value: 42 })],
            true,
        ],
        ['non-finite aggregated value is ignored', [withMissingData({ count: 0, aggregated_value: NaN })], false],
        ['non-zero count with a missing data array', [withMissingData({ count: 5 })], false],
        // Pins the union's current semantics for the ORed contracts (see hasTrendsChartData.ts):
        // an aggregated-value-zero result with a non-zero count still counts as having data.
        [
            'an aggregated-value-zero result with a non-zero count is still treated as having data',
            [makeResult({ aggregated_value: 0, count: 5, data: [] })],
            true,
        ],
        [
            'lifecycle dormant series carries a negative count and still counts as data',
            [makeResult({ data: [-3, -1, 0], count: -4 })],
            true,
        ],
    ])('%s', (_name, results, expected) => {
        expect(hasTrendsChartData(results)).toBe(expected)
    })
})
