import { describe, expect, it } from 'vitest'

import { buildTimeSeriesChartData } from '@/lib/time-series-chart-data'

const DAYS = ['2026-11-10', '2026-11-11', '2026-11-12']

function seriesOf(result: unknown): unknown {
    const block = buildTimeSeriesChartData(result)
    return block === undefined ? undefined : JSON.parse(block).series
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
        ['a trends text table with an in-progress row', 'Date|count\n2026-11-10|5\n2026-11-11 (partial)|3'],
    ])('returns nothing for %s', (_label, result) => {
        expect(buildTimeSeriesChartData(result)).toBeUndefined()
    })
})
