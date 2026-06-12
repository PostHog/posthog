import { describe, expect, it } from 'vitest'

import {
    inferVisualizationType,
    isFunnelResult,
    isHogQLResult,
    isLifecycleResult,
    isPathsResult,
    isRetentionResult,
    isTrendsResult,
} from '@/ui-apps/components/infer-visualization'

// Fixtures mirror the shapes the /query/ endpoint returns for each insight kind,
// reduced to the fields the type guards inspect.

const trendsResults = [
    {
        action: { name: '$pageview' },
        label: '$pageview',
        count: 210,
        data: [10, 80, 120],
        labels: ['1-Jun-2025', '2-Jun-2025', '3-Jun-2025'],
        days: ['2025-06-01', '2025-06-02', '2025-06-03'],
    },
]

const boldNumberResults = [
    {
        action: { name: '$pageview' },
        label: '$pageview',
        aggregated_value: 1234,
        data: [],
        labels: [],
        days: [],
    },
]

const lifecycleResults = [
    { status: 'new', label: '$pageview - new', data: [5, 8], days: ['2025-06-01', '2025-06-02'] },
    { status: 'dormant', label: '$pageview - dormant', data: [-3, -1], days: ['2025-06-01', '2025-06-02'] },
]

const funnelResults = [
    { action_id: '$pageview', name: '$pageview', order: 0, count: 100, type: 'events' },
    { action_id: 'sign_up', name: 'sign_up', order: 1, count: 42, type: 'events' },
]

const breakdownFunnelResults = [
    [
        { action_id: '$pageview', name: '$pageview', order: 0, count: 60, breakdown_value: 'Chrome' },
        { action_id: 'sign_up', name: 'sign_up', order: 1, count: 25, breakdown_value: 'Chrome' },
    ],
    [
        { action_id: '$pageview', name: '$pageview', order: 0, count: 40, breakdown_value: 'Firefox' },
        { action_id: 'sign_up', name: 'sign_up', order: 1, count: 17, breakdown_value: 'Firefox' },
    ],
]

const retentionResults = [
    { date: '2025-06-01T00:00:00Z', label: 'Day 0', values: [{ count: 10 }, { count: 6 }, { count: 4 }] },
    { date: '2025-06-02T00:00:00Z', label: 'Day 1', values: [{ count: 12 }, { count: 5 }] },
]

const pathsResults = [
    { source: '1_/home', target: '2_/pricing', value: 35, average_conversion_time: 1200 },
    { source: '2_/pricing', target: '3_/signup', value: 12, average_conversion_time: 900 },
]

const hogqlResults = {
    columns: ['event', 'count'],
    results: [
        ['$pageview', 100],
        ['sign_up', 42],
    ],
}

describe('inferVisualizationType', () => {
    describe('inference from result shape', () => {
        it.each([
            ['trends', trendsResults, 'trends'],
            ['bold-number trends (aggregated_value with empty data)', boldNumberResults, 'trends'],
            ['lifecycle', lifecycleResults, 'lifecycle'],
            ['flat funnel', funnelResults, 'funnel'],
            ['breakdown funnel (nested arrays)', breakdownFunnelResults, 'funnel'],
            ['retention', retentionResults, 'retention'],
            ['paths', pathsResults, 'paths'],
            ['hogql table', hogqlResults, 'table'],
        ] as const)('classifies %s results', (_label, results, expected) => {
            expect(inferVisualizationType({ results })).toBe(expected)
        })

        it('classifies lifecycle before trends even though rows also match the trends shape', () => {
            expect(isTrendsResult(lifecycleResults)).toBe(true)
            expect(inferVisualizationType({ results: lifecycleResults })).toBe('lifecycle')
        })

        it('classifies retention before trends', () => {
            expect(inferVisualizationType({ query: { kind: 'TrendsQuery' }, results: retentionResults })).toBe(
                'retention'
            )
        })

        it('accepts a brand-new retention cohort with an empty values array', () => {
            const results = [{ date: '2025-06-01T00:00:00Z', label: 'Day 0', values: [] }]
            expect(inferVisualizationType({ results })).toBe('retention')
        })

        it('classifies trends-mode funnel results (data/days arrays) as trends', () => {
            // Funnels in trends visualization mode return time-series rows; the shape check
            // intentionally wins over the FunnelsQuery kind so they render as a line chart.
            const results = [{ data: [0.31, 0.42], days: ['2025-06-01', '2025-06-02'], count: 0 }]
            expect(inferVisualizationType({ query: { kind: 'FunnelsQuery' }, results })).toBe('trends')
        })
    })

    describe('fallback to query kind', () => {
        it.each([
            ['TrendsQuery', 'trends'],
            ['FunnelsQuery', 'funnel'],
            ['LifecycleQuery', 'lifecycle'],
            ['RetentionQuery', 'retention'],
            ['PathsQuery', 'paths'],
            ['HogQLQuery', 'table'],
        ] as const)('falls back to %s when results are empty', (kind, expected) => {
            expect(inferVisualizationType({ query: { kind }, results: [] })).toBe(expected)
        })

        it('falls back to the query kind when results is a formatted string', () => {
            // insight-query with output_format=optimized currently puts the server-side
            // formatted summary (a string) into `results`; only the kind fallback fires.
            const data = { query: { kind: 'TrendsQuery' }, results: 'Date | $pageview\n2025-06-01 | 10' }
            expect(inferVisualizationType(data)).toBe('trends')
        })

        it('returns null for StickinessQuery with empty results', () => {
            // Known gap: query-stickiness ships the query-results UI app but the dispatcher
            // has no StickinessQuery fallback — empty stickiness results show "unsupported".
            expect(inferVisualizationType({ query: { kind: 'StickinessQuery' }, results: [] })).toBeNull()
        })

        it('classifies non-empty stickiness results as trends via the shape check', () => {
            const results = [{ label: '$pageview', data: [40, 25, 10], days: [1, 2, 3], count: 75 }]
            expect(inferVisualizationType({ query: { kind: 'StickinessQuery' }, results })).toBe('trends')
        })

        it('falls back to FunnelsQuery for time-to-convert results (bins object)', () => {
            const results = { bins: [[30, 5] as const, [60, 2] as const], average_conversion_time: 45 }
            expect(inferVisualizationType({ query: { kind: 'FunnelsQuery' }, results })).toBe('funnel')
        })
    })

    describe('unclassifiable input', () => {
        it.each([
            ['null', null],
            ['undefined', undefined],
            ['a string payload', 'plain text'],
            ['a number', 42],
            ['an empty object', {}],
            ['unknown query kind with empty results', { query: { kind: 'MysteryQuery' }, results: [] }],
            ['rows matching no known shape', { results: [{ foo: 'bar' }] }],
        ] as const)('returns null for %s', (_label, data) => {
            expect(inferVisualizationType(data)).toBeNull()
        })
    })

    describe('type guards', () => {
        it.each([
            ['isTrendsResult', isTrendsResult, trendsResults],
            ['isLifecycleResult', isLifecycleResult, lifecycleResults],
            ['isFunnelResult', isFunnelResult, funnelResults],
            ['isRetentionResult', isRetentionResult, retentionResults],
            ['isPathsResult', isPathsResult, pathsResults],
            ['isHogQLResult', isHogQLResult, hogqlResults],
        ] as const)('%s accepts its own shape and rejects empties and non-arrays', (_label, guard, fixture) => {
            expect(guard(fixture)).toBe(true)
            expect(guard([])).toBe(false)
            expect(guard(null)).toBe(false)
            expect(guard('text')).toBe(false)
        })

        it('isFunnelResult rejects a nested format whose first breakdown is empty', () => {
            expect(isFunnelResult([[]])).toBe(false)
        })

        it('isLifecycleResult rejects trends rows without a lifecycle status', () => {
            expect(isLifecycleResult(trendsResults)).toBe(false)
        })

        it('isHogQLResult requires both columns and results to be arrays', () => {
            expect(isHogQLResult({ columns: ['a'], results: 'nope' })).toBe(false)
            expect(isHogQLResult({ columns: ['a'] })).toBe(false)
        })
    })
})
