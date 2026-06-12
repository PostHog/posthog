import { describe, expect, it } from 'vitest'

import {
    formatDate,
    formatDuration,
    formatNumber,
    formatPercent,
    getDisplayType,
    getSeriesLabel,
    isBarChart,
    normalizeFunnelSteps,
} from '@/ui-apps/components/utils'

describe('visualizer utils', () => {
    describe('formatNumber', () => {
        it.each([
            [0, '0'],
            [999, '999'],
            [1000, '1.0K'],
            [1500, '1.5K'],
            [999_999, '1000.0K'],
            [1_000_000, '1.0M'],
            [2_345_678, '2.3M'],
        ])('formats %d as %s', (value, expected) => {
            expect(formatNumber(value)).toBe(expected)
        })
    })

    describe('formatPercent', () => {
        it.each([
            [0, '0.0%'],
            [0.123, '12.3%'],
            [0.1234, '12.3%'],
            [1, '100.0%'],
        ])('formats %d as %s', (value, expected) => {
            expect(formatPercent(value)).toBe(expected)
        })
    })

    describe('formatDuration', () => {
        it.each([
            [0, '0s'],
            [-5000, '0s'],
            [Number.NaN, '0s'],
            [Number.POSITIVE_INFINITY, '0s'],
            [34_000, '34s'],
            [94_000, '1m 34s'],
            [3_600_000, '1h'],
            [3_660_000, '1h 1m'],
            // Only the two most-significant units are kept: 1d 1h 1m 1s → "1d 1h".
            [90_061_000, '1d 1h'],
        ])('formats %dms as %s', (ms, expected) => {
            expect(formatDuration(ms)).toBe(expected)
        })
    })

    describe('formatDate', () => {
        it('formats ISO date strings as a short month + day', () => {
            // Noon, no timezone suffix — parses as local time so the day is stable in any test TZ.
            expect(formatDate('2025-06-01T12:00:00')).toBe('Jun 1')
        })

        it.each([['Day 1'], ['1 day'], ['Week 3'], ['']])(
            'passes through pre-formatted label %j unchanged',
            (label) => {
                expect(formatDate(label)).toBe(label)
            }
        )

        it('passes through strings with an ISO prefix that fail to parse', () => {
            expect(formatDate('2025-99-99')).toBe('2025-99-99')
        })
    })

    describe('getSeriesLabel', () => {
        it('prefers label, then action name, then a positional fallback', () => {
            expect(getSeriesLabel({ label: 'Pageviews', action: { name: '$pageview' } }, 0)).toBe('Pageviews')
            expect(getSeriesLabel({ action: { name: '$pageview' } }, 0)).toBe('$pageview')
            expect(getSeriesLabel({}, 2)).toBe('Series 3')
        })
    })

    describe('getDisplayType / isBarChart', () => {
        it('defaults to ActionsLineGraph when the query or filter is missing', () => {
            expect(getDisplayType(undefined)).toBe('ActionsLineGraph')
            expect(getDisplayType({ kind: 'TrendsQuery' })).toBe('ActionsLineGraph')
        })

        it('reads the display type from trendsFilter', () => {
            expect(getDisplayType({ kind: 'TrendsQuery', trendsFilter: { display: 'BoldNumber' } })).toBe('BoldNumber')
        })

        it.each([
            ['ActionsBar', true],
            ['ActionsBarValue', true],
            ['ActionsLineGraph', false],
            ['BoldNumber', false],
        ] as const)('isBarChart(%s) is %s', (displayType, expected) => {
            expect(isBarChart(displayType)).toBe(expected)
        })
    })

    describe('normalizeFunnelSteps', () => {
        const steps = [
            { name: '$pageview', order: 0, count: 100 },
            { name: 'sign_up', custom_name: 'Signed up', order: 1, count: 42 },
        ]

        it('returns an empty array for empty results', () => {
            expect(normalizeFunnelSteps([])).toEqual([])
        })

        it('normalizes a flat steps array, preferring custom_name', () => {
            expect(normalizeFunnelSteps(steps)).toEqual([
                { name: '$pageview', count: 100, order: 0 },
                { name: 'Signed up', count: 42, order: 1 },
            ])
        })

        it('fills missing name, count, and order with defaults', () => {
            expect(normalizeFunnelSteps([{}, { count: 7 }])).toEqual([
                { name: 'Step 1', count: 0, order: 0 },
                { name: 'Step 2', count: 7, order: 1 },
            ])
        })

        it('uses only the first series of a breakdown funnel', () => {
            // Known limitation: remaining breakdown series are dropped rather than
            // aggregated, so the chart shows a single breakdown's counts.
            const breakdown = [
                [
                    { name: '$pageview', order: 0, count: 60, breakdown_value: 'Chrome' },
                    { name: 'sign_up', order: 1, count: 25, breakdown_value: 'Chrome' },
                ],
                [
                    { name: '$pageview', order: 0, count: 40, breakdown_value: 'Firefox' },
                    { name: 'sign_up', order: 1, count: 17, breakdown_value: 'Firefox' },
                ],
            ]
            expect(normalizeFunnelSteps(breakdown)).toEqual([
                { name: '$pageview', count: 60, order: 0 },
                { name: 'sign_up', count: 25, order: 1 },
            ])
        })
    })
})
