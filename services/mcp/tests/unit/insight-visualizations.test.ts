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
import {
    formatDate,
    formatDuration,
    formatNumber,
    formatPercent,
    getDisplayType,
    getSeriesLabel,
    normalizeFunnelSteps,
} from '@/ui-apps/components/utils'

import { insightResults, queryPayload } from '../fixtures/insight-fixtures'

describe('insight visualizations', () => {
    describe('inferVisualizationType', () => {
        describe('inference from result shape (captured API fixtures)', () => {
            it.each([
                ['trends line', insightResults.trendsLine, 'trends'],
                ['trends line with breakdown', insightResults.trendsLineBreakdown, 'trends'],
                ['bold-number trends (aggregated_value)', insightResults.trendsNumber, 'trends'],
                ['pie-display trends', insightResults.trendsPie, 'trends'],
                ['world-map trends', insightResults.trendsWorldMap, 'trends'],
                ['stickiness (duck-types as trends)', insightResults.stickiness, 'trends'],
                ['lifecycle', insightResults.lifecycle, 'lifecycle'],
                ['flat funnel', insightResults.funnelTopToBottom, 'funnel'],
                ['breakdown funnel (nested arrays)', insightResults.funnelTopToBottomBreakdown, 'funnel'],
                ['retention', insightResults.retention, 'retention'],
                ['paths', insightResults.userPaths, 'paths'],
                ['hogql table', insightResults.hogqlTable, 'table'],
            ] as const)('classifies %s results', (_label, results, expected) => {
                expect(inferVisualizationType(queryPayload(results))).toBe(expected)
            })

            it('classifies lifecycle before trends even though rows also match the trends shape', () => {
                expect(isTrendsResult(insightResults.lifecycle)).toBe(true)
                expect(inferVisualizationType(queryPayload(insightResults.lifecycle))).toBe('lifecycle')
            })

            it('classifies retention before trends', () => {
                expect(inferVisualizationType(queryPayload(insightResults.retention, 'TrendsQuery'))).toBe('retention')
            })

            it('accepts a brand-new retention cohort with an empty values array', () => {
                const results = [{ date: '2025-06-01T00:00:00Z', label: 'Day 0', values: [] }]
                expect(inferVisualizationType(queryPayload(results))).toBe('retention')
            })

            it('classifies trends-mode funnel results (data/days arrays) as trends', () => {
                // Funnels in trends visualization mode return time-series rows; the shape check
                // intentionally wins over the FunnelsQuery kind so they render as a line chart.
                expect(
                    inferVisualizationType(queryPayload(insightResults.funnelHistoricalTrends, 'FunnelsQuery'))
                ).toBe('trends')
            })
        })

        describe('fallback to query kind', () => {
            it.each([
                ['TrendsQuery', 'trends'],
                ['StickinessQuery', 'stickiness'],
                ['FunnelsQuery', 'funnel'],
                ['LifecycleQuery', 'lifecycle'],
                ['RetentionQuery', 'retention'],
                ['PathsQuery', 'paths'],
                ['HogQLQuery', 'table'],
            ] as const)('falls back to %s when results are empty', (kind, expected) => {
                expect(inferVisualizationType(queryPayload([], kind))).toBe(expected)
            })

            it('falls back to the query kind when results is a formatted string', () => {
                // If a formatted summary (a string) ever reaches the UI app as `results`, the
                // structural guards can't match and only the kind fallback can classify it.
                const data = queryPayload('Date | $pageview\n2025-06-01 | 10', 'TrendsQuery')
                expect(inferVisualizationType(data)).toBe('trends')
            })

            it.each([
                ['DataVisualizationNode wrapping HogQLQuery', 'DataVisualizationNode', 'HogQLQuery', 'table'],
                ['InsightVizNode wrapping TrendsQuery', 'InsightVizNode', 'TrendsQuery', 'trends'],
                ['InsightVizNode wrapping StickinessQuery', 'InsightVizNode', 'StickinessQuery', 'stickiness'],
                ['InsightVizNode wrapping RetentionQuery', 'InsightVizNode', 'RetentionQuery', 'retention'],
            ] as const)('unwraps %s to its inner kind', (_label, wrapperKind, sourceKind, expected) => {
                // Wrapper nodes carry the real query kind on `source.kind`; the fallback must
                // unwrap so a formatted-string payload still resolves to the right visualization.
                const data = { query: { kind: wrapperKind, source: { kind: sourceKind } }, results: 'col\n1' }
                expect(inferVisualizationType(data)).toBe(expected)
            })

            it('returns null for a wrapper node with no source kind', () => {
                const data = { query: { kind: 'DataVisualizationNode' }, results: 'col\n1' }
                expect(inferVisualizationType(data)).toBeNull()
            })

            it('classifies stickiness results as stickiness, not trends, via the query kind', () => {
                // Stickiness rows duck-type as trends, so the kind check must win — otherwise the
                // chart renders raw counts instead of the percentage-of-users distribution.
                expect(inferVisualizationType(queryPayload(insightResults.stickiness, 'StickinessQuery'))).toBe(
                    'stickiness'
                )
            })

            it('falls back to FunnelsQuery for time-to-convert results (bins object)', () => {
                expect(inferVisualizationType(queryPayload(insightResults.funnelTimeToConvert, 'FunnelsQuery'))).toBe(
                    'funnel'
                )
            })
        })

        describe('unclassifiable input', () => {
            it.each([
                ['null', null],
                ['undefined', undefined],
                ['a string payload', 'plain text'],
                ['a number', 42],
                ['an empty object', {}],
                ['unknown query kind with empty results', queryPayload([], 'MysteryQuery')],
                ['rows matching no known shape', queryPayload([{ foo: 'bar' }])],
            ] as const)('returns null for %s', (_label, data) => {
                expect(inferVisualizationType(data)).toBeNull()
            })
        })

        describe('type guards', () => {
            it.each([
                ['isTrendsResult', isTrendsResult, insightResults.trendsLine],
                ['isLifecycleResult', isLifecycleResult, insightResults.lifecycle],
                ['isFunnelResult', isFunnelResult, insightResults.funnelTopToBottom],
                ['isRetentionResult', isRetentionResult, insightResults.retention],
                ['isPathsResult', isPathsResult, insightResults.userPaths],
                ['isHogQLResult', isHogQLResult, insightResults.hogqlTable],
            ] as const)('%s accepts its own shape and rejects empties and non-arrays', (_label, guard, fixture) => {
                expect(guard(fixture)).toBe(true)
                expect(guard([])).toBe(false)
                expect(guard(null)).toBe(false)
                expect(guard('text')).toBe(false)
            })

            it('isFunnelResult accepts the nested breakdown format', () => {
                expect(isFunnelResult(insightResults.funnelTopToBottomBreakdown)).toBe(true)
            })

            it('isFunnelResult rejects a nested format whose first breakdown is empty', () => {
                expect(isFunnelResult([[]])).toBe(false)
            })

            it('isLifecycleResult rejects trends rows without a lifecycle status', () => {
                expect(isLifecycleResult(insightResults.trendsLine)).toBe(false)
            })

            it('isHogQLResult requires both columns and results to be arrays', () => {
                expect(isHogQLResult({ columns: ['a'], results: 'nope' })).toBe(false)
                expect(isHogQLResult({ columns: ['a'] })).toBe(false)
            })
        })
    })

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

        describe('getDisplayType', () => {
            it('defaults to ActionsLineGraph when the query or filter is missing', () => {
                expect(getDisplayType(undefined)).toBe('ActionsLineGraph')
                expect(getDisplayType({ kind: 'TrendsQuery' })).toBe('ActionsLineGraph')
            })

            it('reads the display type from trendsFilter', () => {
                expect(getDisplayType({ kind: 'TrendsQuery', trendsFilter: { display: 'BoldNumber' } })).toBe(
                    'BoldNumber'
                )
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
})
