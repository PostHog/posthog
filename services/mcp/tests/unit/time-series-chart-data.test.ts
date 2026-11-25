import { describe, expect, it } from 'vitest'

import { CHART_DATA_PREAMBLE, buildTimeSeriesChartData } from '@/lib/time-series-chart-data'
import { withInformationalResponse } from '@/tools/tool-utils'

const DAYS = ['2026-11-10', '2026-11-11', '2026-11-12']

function seriesOf(result: unknown): unknown {
    const block = buildTimeSeriesChartData(result)
    if (block === undefined) {
        return undefined
    }
    const [preamble, json] = block.split('\n')
    expect(preamble).toBe(CHART_DATA_PREAMBLE)
    return JSON.parse(json!).series
}

describe('buildTimeSeriesChartData', () => {
    it.each([
        [
            'trends series, named by custom_name',
            { results: [{ data: [5, 7, 6], days: DAYS, label: '$pageview', custom_name: 'Pageviews' }] },
            [
                {
                    name: 'Pageviews',
                    data: [
                        ['2026-11-10', 5],
                        ['2026-11-11', 7],
                        ['2026-11-12', 6],
                    ],
                },
            ],
        ],
        [
            'trends breakdown, with the other bucket given its display name',
            {
                results: [
                    { data: [1, 2, 3], days: DAYS, label: 'Chrome', breakdown_value: ['Chrome'] },
                    {
                        data: [4, 5, 6],
                        days: DAYS,
                        label: '$$_posthog_breakdown_other_$$',
                        breakdown_value: ['$$_posthog_breakdown_other_$$'],
                    },
                ],
            },
            [
                {
                    name: 'Chrome',
                    data: [
                        ['2026-11-10', 1],
                        ['2026-11-11', 2],
                        ['2026-11-12', 3],
                    ],
                },
                {
                    name: 'Other',
                    data: [
                        ['2026-11-10', 4],
                        ['2026-11-11', 5],
                        ['2026-11-12', 6],
                    ],
                },
            ],
        ],
        [
            'trends comparison, keeping only the current period',
            {
                results: [
                    { data: [1, 2, 3], days: DAYS, label: 'signups', compare_label: 'current' },
                    {
                        data: [9, 9, 9],
                        days: ['2026-11-07', '2026-11-08', '2026-11-09'],
                        label: 'signups',
                        compare_label: 'previous',
                    },
                ],
            },
            [
                {
                    name: 'signups',
                    data: [
                        ['2026-11-10', 1],
                        ['2026-11-11', 2],
                        ['2026-11-12', 3],
                    ],
                },
            ],
        ],
        [
            'hourly buckets with a time, from a shared axis of labels',
            {
                labels: ['2026-11-10T00:00', '2026-11-10T01:00'],
                series: [
                    { name: 'succeeded', values: [10, 12] },
                    { name: 'failed', values: [0, 1] },
                ],
            },
            [
                {
                    name: 'succeeded',
                    data: [
                        ['2026-11-10T00:00', 10],
                        ['2026-11-10T01:00', 12],
                    ],
                },
                {
                    name: 'failed',
                    data: [
                        ['2026-11-10T00:00', 0],
                        ['2026-11-10T01:00', 1],
                    ],
                },
            ],
        ],
        [
            'metric point lists, named by metric and labels',
            {
                results: [
                    {
                        metric_name: 'http_requests_total',
                        labels: { service: 'api' },
                        points: [
                            { time: '2026-11-17T20:00:00Z', value: 1200.5 },
                            { time: '2026-11-17T20:05:00Z', value: 1302 },
                        ],
                    },
                ],
            },
            [
                {
                    name: 'http_requests_total service=api',
                    data: [
                        ['2026-11-17T20:00:00Z', 1200.5],
                        ['2026-11-17T20:05:00Z', 1302],
                    ],
                },
            ],
        ],
        [
            'long-format rows, split into one series per text value',
            [
                { time: '2026-11-17T19:34:00Z', severity: 'info', count: 100 },
                { time: '2026-11-17T19:34:00Z', severity: 'error', count: 3 },
                { time: '2026-11-17T19:36:00Z', severity: 'info', count: 120 },
                { time: '2026-11-17T19:36:00Z', severity: 'error', count: 5 },
            ],
            [
                {
                    name: 'info',
                    data: [
                        ['2026-11-17T19:34:00Z', 100],
                        ['2026-11-17T19:36:00Z', 120],
                    ],
                },
                {
                    name: 'error',
                    data: [
                        ['2026-11-17T19:34:00Z', 3],
                        ['2026-11-17T19:36:00Z', 5],
                    ],
                },
            ],
        ],
        [
            'wide rows, one series per numeric column',
            {
                results: [
                    { day: '2026-11-10 00:00:00', calls: 10, errors: 1 },
                    { day: '2026-11-11 00:00:00', calls: 12, errors: 0 },
                ],
            },
            [
                {
                    name: 'calls',
                    data: [
                        ['2026-11-10', 10],
                        ['2026-11-11', 12],
                    ],
                },
                {
                    name: 'errors',
                    data: [
                        ['2026-11-10', 1],
                        ['2026-11-11', 0],
                    ],
                },
            ],
        ],
        [
            'an execute-sql text table between notices, newest row first',
            {
                query: { kind: 'HogQLQuery', query: 'SELECT ...' },
                results: [
                    'Warning: event "signup" was not seen in the last 30 days.',
                    'day|calls|users',
                    '2026-11-11T00:00:00-08:00|12|(null)',
                    '2026-11-10T00:00:00-08:00|10|4',
                    '[SQL result preview: Showing 2 of 9 returned rows.]',
                    '',
                    '',
                    '[Warehouse suggestions for views this query read.]',
                    '- Sync the `orders` table to query revenue.',
                ].join('\n'),
            },
            [
                {
                    name: 'calls',
                    data: [
                        ['2026-11-10', 10],
                        ['2026-11-11', 12],
                    ],
                },
            ],
        ],
        [
            'hourly buckets in the project timezone, as wall-clock times',
            {
                results: ['hour|calls', '2026-11-10T13:00:00-08:00|4', '2026-11-10T14:00:00-08:00|6'].join('\n'),
            },
            [
                {
                    name: 'calls',
                    data: [
                        ['2026-11-10T13:00:00', 4],
                        ['2026-11-10T14:00:00', 6],
                    ],
                },
            ],
        ],
        [
            'count ranges, ignoring the end of each bucket',
            {
                ranges: [
                    { date_from: '2026-11-10T00:00:00Z', date_to: '2026-11-10T01:00:00Z', count: 4 },
                    { date_from: '2026-11-10T01:00:00Z', date_to: '2026-11-10T02:00:00Z', count: 6 },
                ],
            },
            [
                {
                    name: 'count',
                    data: [
                        ['2026-11-10T00:00:00Z', 4],
                        ['2026-11-10T01:00:00Z', 6],
                    ],
                },
            ],
        ],
        [
            'an execute-sql text table grouped by a second date column',
            {
                results: [
                    'day|signup_date|users',
                    '2026-11-10|2026-11-01|5',
                    '2026-11-11|2026-11-01|6',
                    '2026-11-10|2026-11-02|7',
                    '2026-11-11|2026-11-02|8',
                ].join('\n'),
            },
            [
                {
                    name: '2026-11-01',
                    data: [
                        ['2026-11-10', 5],
                        ['2026-11-11', 6],
                    ],
                },
                {
                    name: '2026-11-02',
                    data: [
                        ['2026-11-10', 7],
                        ['2026-11-11', 8],
                    ],
                },
            ],
        ],
        [
            'an execute-sql text table with NULL and empty groups kept apart',
            {
                results: [
                    'day|vendor|calls',
                    '2026-11-10|(null)|1',
                    '2026-11-11|(null)|2',
                    '2026-11-10||3',
                    '2026-11-11||4',
                ].join('\n'),
            },
            [
                {
                    name: '(null)',
                    data: [
                        ['2026-11-10', 1],
                        ['2026-11-11', 2],
                    ],
                },
                {
                    name: '(empty)',
                    data: [
                        ['2026-11-10', 3],
                        ['2026-11-11', 4],
                    ],
                },
            ],
        ],
        [
            'an execute-sql text table in long format, split by its text and ID columns',
            {
                results: [
                    'bucket|team_id|vendor|calls',
                    '2026-11-10|2|ClaudeCode|7',
                    '2026-11-11|2|ClaudeCode|9',
                    '2026-11-10|2|Cowork|3',
                    '2026-11-11|2|Cowork|4',
                ].join('\n'),
            },
            [
                {
                    name: 'team_id=2, ClaudeCode',
                    data: [
                        ['2026-11-10', 7],
                        ['2026-11-11', 9],
                    ],
                },
                {
                    name: 'team_id=2, Cowork',
                    data: [
                        ['2026-11-10', 3],
                        ['2026-11-11', 4],
                    ],
                },
            ],
        ],
    ])('charts %s', (_label, result, expected) => {
        expect(seriesOf(result)).toEqual(expected)
    })

    it.each([
        ['stickiness, whose days are interval counts', { results: [{ data: [9, 4, 1], days: [1, 2, 3] }] }],
        ['a total-value trend with no points', { results: [{ data: [], days: DAYS, aggregated_value: 12 }] }],
        ['a series with one label that is not a date', { results: [{ data: [1, 2], days: ['2026-11-10', 'Total'] }] }],
        [
            'retention cohorts',
            { results: [{ date: '2026-11-10T00:00:00Z', label: 'Day 0', values: [{ count: 4 }, { count: 2 }] }] },
        ],
        [
            'more series than one chart can name',
            {
                results: Array.from({ length: 26 }, (_, index) => ({
                    data: [1, 2, 3],
                    days: DAYS,
                    label: `s${index}`,
                })),
            },
        ],
        ['a text table with one row', 'Date|count\n2026-11-10|5'],
        ['a text table with no time column', { results: 'browser|count\nChrome|5\nSafari|3' }],
        [
            'more points than one block can carry',
            {
                results: [
                    {
                        data: Array.from({ length: 3000 }, () => 1),
                        days: Array.from({ length: 3000 }, () => '2026-11-10'),
                        label: 'pageviews',
                    },
                ],
            },
        ],
        [
            'a text table with more series than one chart can name',
            {
                results: [
                    ['day', ...Array.from({ length: 30 }, (_, index) => `metric_${index}`)].join('|'),
                    ['2026-11-10', ...Array.from({ length: 30 }, () => '1')].join('|'),
                    ['2026-11-11', ...Array.from({ length: 30 }, () => '2')].join('|'),
                ].join('\n'),
            },
        ],
        [
            'an execute-sql text table with a pipe inside a cell',
            {
                results: [
                    'day|path|views',
                    '2026-11-10|/home|5',
                    '2026-11-11|/home|6',
                    '2026-11-12|/a|b|7',
                    '2026-11-13|/home|8',
                ].join('\n'),
            },
        ],
        [
            'an informational response, whose labels sit inside a fence',
            withInformationalResponse(
                { results: [{ data: [1, 2], dates: DAYS.slice(0, 2), label: 'Project A' }] },
                'billing'
            ),
        ],
        ['a trends text table with an in-progress row', 'Date|count\n2026-11-10|5\n2026-11-11 (partial)|3'],
        [
            'an execute-sql text table whose last cell continues on a new line',
            {
                results: [
                    'day|views|browser',
                    '2026-11-10|5|Chrome',
                    '2026-11-11|6|Chrome',
                    '2026-11-12|7|Chrome',
                    'Safari',
                ].join('\n'),
            },
        ],
        [
            'an execute-sql text table split by a numeric hour',
            { results: 'day|hour|events\n2026-11-10|0|5\n2026-11-10|1|7\n2026-11-11|0|6\n2026-11-11|1|8' },
        ],
        [
            'rows split by a numeric status code',
            {
                results: [
                    { day: '2026-11-10', status: 200, events: 50 },
                    { day: '2026-11-10', status: 404, events: 3 },
                    { day: '2026-11-11', status: 200, events: 60 },
                    { day: '2026-11-11', status: 404, events: 2 },
                ],
            },
        ],
    ])('returns nothing for %s', (_label, result) => {
        expect(buildTimeSeriesChartData(result)).toBeUndefined()
    })
})
