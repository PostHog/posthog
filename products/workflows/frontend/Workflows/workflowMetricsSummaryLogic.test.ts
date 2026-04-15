import { AppMetricsTimeSeriesResponse, AppMetricsTotalsResponse } from 'lib/components/AppMetrics/appMetricsLogic'

import { calculateInProgressTotal, subtractSeries, withDisplayName } from './workflowMetricsSummaryLogic'

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

describe('calculateInProgressTotal', () => {
    const totals = (rows: Record<string, number>): AppMetricsTotalsResponse =>
        Object.fromEntries(Object.entries(rows).map(([key, total]) => [key, { total, breakdowns: [key] }]))

    it.each([
        {
            name: 'returns triggered count when nothing has terminated',
            triggered: totals({ triggered: 10 }),
            terminated: {},
            expected: 10,
        },
        {
            name: 'subtracts succeeded from triggered',
            triggered: totals({ triggered: 10 }),
            terminated: totals({ succeeded: 7 }),
            expected: 3,
        },
        {
            name: 'subtracts succeeded + failed + early_exit from triggered',
            triggered: totals({ triggered: 10 }),
            terminated: totals({ succeeded: 4, failed: 3, early_exit: 2 }),
            expected: 1,
        },
        {
            name: 'clamps to zero when terminated exceeds triggered (metric lag)',
            triggered: totals({ triggered: 5 }),
            terminated: totals({ succeeded: 3, failed: 4 }),
            expected: 0,
        },
        {
            name: 'returns zero when both are empty',
            triggered: {},
            terminated: {},
            expected: 0,
        },
    ])('$name', ({ triggered, terminated, expected }) => {
        expect(calculateInProgressTotal(triggered, terminated)).toBe(expected)
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
