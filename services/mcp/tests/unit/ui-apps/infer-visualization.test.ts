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

import { insightResults, queryPayload } from '../../fixtures/insight-fixtures'

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
            expect(inferVisualizationType(queryPayload(insightResults.funnelHistoricalTrends, 'FunnelsQuery'))).toBe(
                'trends'
            )
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
            expect(inferVisualizationType(queryPayload([], kind))).toBe(expected)
        })

        it('falls back to the query kind when results is a formatted string', () => {
            // insight-query with output_format=optimized currently puts the server-side
            // formatted summary (a string) into `results`; only the kind fallback fires.
            const data = queryPayload('Date | $pageview\n2025-06-01 | 10', 'TrendsQuery')
            expect(inferVisualizationType(data)).toBe('trends')
        })

        it('returns null for StickinessQuery with empty results', () => {
            // Known gap: query-stickiness ships the query-results UI app but the dispatcher
            // has no StickinessQuery fallback — empty stickiness results show "unsupported".
            expect(inferVisualizationType(queryPayload([], 'StickinessQuery'))).toBeNull()
        })

        it('classifies non-empty stickiness results as trends via the shape check', () => {
            expect(inferVisualizationType(queryPayload(insightResults.stickiness, 'StickinessQuery'))).toBe('trends')
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
