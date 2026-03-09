import { AppMetricsTimeSeriesResponse } from 'lib/components/AppMetrics/appMetricsLogic'

import { subtractSeries, withDisplayName } from './workflowMetricsSummaryLogic'

const series = (labels: string[], ...namedValues: [string, number[]][]): AppMetricsTimeSeriesResponse => ({
    labels,
    series: namedValues.map(([name, values]) => ({ name, values })),
})

describe('withDisplayName', () => {
    it.each([
        {
            name: 'returns null for null input',
            input: null,
            displayName: 'Custom',
            expected: null,
        },
        {
            name: 'replaces name on single series',
            input: series(['day1', 'day2'], ['original', [1, 2]]),
            displayName: 'Renamed',
            expected: series(['day1', 'day2'], ['Renamed', [1, 2]]),
        },
        {
            name: 'replaces name on multiple series',
            input: series(['day1'], ['a', [1]], ['b', [2]]),
            displayName: 'All same',
            expected: series(['day1'], ['All same', [1]], ['All same', [2]]),
        },
    ])('$name', ({ input, displayName, expected }) => {
        expect(withDisplayName(input, displayName)).toEqual(expected)
    })
})

describe('subtractSeries', () => {
    it.each([
        {
            name: 'both null returns null',
            minuend: null,
            subtrahend: null,
            displayName: 'Result',
            expected: null,
        },
        {
            name: 'null subtrahend uses zeros',
            minuend: series(['d1', 'd2'], ['sent', [5, 10]]),
            subtrahend: null,
            displayName: 'Delivered',
            expected: series(['d1', 'd2'], ['Delivered', [5, 10]]),
        },
        {
            name: 'null minuend uses zeros',
            minuend: null,
            subtrahend: series(['d1', 'd2'], ['failed', [3, 7]]),
            displayName: 'Delivered',
            expected: series(['d1', 'd2'], ['Delivered', [0, 0]]),
        },
        {
            name: 'subtracts values element-wise',
            minuend: series(['d1', 'd2', 'd3'], ['sent', [10, 20, 30]]),
            subtrahend: series(['d1', 'd2', 'd3'], ['failed', [2, 5, 10]]),
            displayName: 'Delivered',
            expected: series(['d1', 'd2', 'd3'], ['Delivered', [8, 15, 20]]),
        },
        {
            name: 'clamps negative results to zero',
            minuend: series(['d1', 'd2'], ['sent', [1, 0]]),
            subtrahend: series(['d1', 'd2'], ['failed', [5, 3]]),
            displayName: 'Delivered',
            expected: series(['d1', 'd2'], ['Delivered', [0, 0]]),
        },
    ])('$name', ({ minuend, subtrahend, displayName, expected }) => {
        expect(subtractSeries(minuend, subtrahend, displayName)).toEqual(expected)
    })
})
