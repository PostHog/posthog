import { AppMetricsTimeSeriesResponse } from 'lib/components/AppMetrics/appMetricsLogic'

import {
    type EmailMetric,
    buildEmailMetricInvocationSearchParams,
    subtractSeries,
    withDisplayName,
} from './workflowMetricsSummaryLogic'

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

describe('buildEmailMetricInvocationSearchParams', () => {
    const dateFrom = '2026-07-01T00:00:00.000Z'
    const dateTo = '2026-07-13T00:00:00.000Z'

    // Each metric drills into the Invocations tab via the unified search box (`inv_search`), narrowed
    // to the level that distinguishes it: bounced/blocked at WARN/ERROR, bounce prevented
    // ("Skipping send") at INFO.
    it.each<[EmailMetric, Record<string, string>]>([
        [
            'email_bounced',
            { inv_date_from: dateFrom, inv_date_to: dateTo, inv_search: 'bounce', inv_log_levels: 'WARN,ERROR' },
        ],
        [
            'email_blocked',
            { inv_date_from: dateFrom, inv_date_to: dateTo, inv_search: 'Complaint', inv_log_levels: 'WARN,ERROR' },
        ],
        [
            'email_bounce_prevented',
            { inv_date_from: dateFrom, inv_date_to: dateTo, inv_search: 'Skipping send', inv_log_levels: 'INFO' },
        ],
    ])('maps %s to the expected Invocations-tab params', (metricKey, expected) => {
        expect(buildEmailMetricInvocationSearchParams(metricKey, dateFrom, dateTo)).toEqual(expected)
    })

    it.each<EmailMetric>(['email_sent', 'email_delivered', 'email_opened', 'email_failed'])(
        'returns null for the non-drillable metric %s',
        (metricKey) => {
            expect(buildEmailMetricInvocationSearchParams(metricKey, dateFrom, dateTo)).toBeNull()
        }
    )
})
