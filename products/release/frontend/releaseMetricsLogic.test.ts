import { metricFromResult } from './releaseMetricsLogic'

describe('metricFromResult', () => {
    it.each([
        {
            name: 'a trend uses its last point and its days as labels',
            result: [{ data: [3, 5, 8], days: ['2026-11-01', '2026-11-02', '2026-11-03'], labels: ['1', '2', '3'] }],
            expected: { value: 8, values: [3, 5, 8], labels: ['2026-11-01', '2026-11-02', '2026-11-03'] },
        },
        {
            name: 'an aggregated value wins over the last point',
            result: [{ data: [3, 5], days: ['a', 'b'], aggregated_value: 42 }],
            expected: { value: 42, values: [3, 5], labels: ['a', 'b'] },
        },
        {
            name: 'a result that is not a trend has no value',
            result: { results: [] },
            expected: { value: null, values: [], labels: [] },
        },
    ])('$name', ({ result, expected }) => {
        expect(metricFromResult(result)).toEqual(expected)
    })
})
