import { describe, expect, it } from 'vitest'

import { inferVisualizationType } from '../../src/ui-apps/components/infer-visualization'

describe('inferVisualizationType', () => {
    describe('structural inference from results', () => {
        it.each([
            ['HogQL table', { results: { columns: ['a'], results: [[1]] } }, 'table'],
            ['trends', { results: [{ data: [1, 2], labels: ['a', 'b'] }] }, 'trends'],
            ['funnel', { results: [{ name: 'step', count: 5, order: 0 }] }, 'funnel'],
            ['lifecycle', { results: [{ status: 'returning', data: [1] }] }, 'lifecycle'],
            ['retention', { results: [{ date: '2026-01-01', values: [{ count: 3 }] }] }, 'retention'],
            ['paths', { results: [{ source: '1_a', target: '2_b', value: 4 }] }, 'paths'],
        ])('detects %s from result shape', (_label, data, expected) => {
            expect(inferVisualizationType(data)).toBe(expected)
        })
    })

    describe('query-kind fallback when results are not structurally inferrable', () => {
        // optimized output replaces structured results with a formatted string, so the
        // structural guards can't fire and inference must rely on the query kind.
        const formatted = 'col_a|col_b\n1|2'

        it.each([
            ['TrendsQuery', 'trends'],
            ['FunnelsQuery', 'funnel'],
            ['RetentionQuery', 'retention'],
            ['PathsQuery', 'paths'],
            ['LifecycleQuery', 'lifecycle'],
            ['HogQLQuery', 'table'],
        ])('falls back to %s -> %s', (kind, expected) => {
            expect(inferVisualizationType({ query: { kind }, results: formatted })).toBe(expected)
        })

        it('unwraps DataVisualizationNode to its inner HogQL kind', () => {
            const data = {
                query: { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery' } },
                results: formatted,
            }
            expect(inferVisualizationType(data)).toBe('table')
        })

        it.each([
            ['TrendsQuery', 'trends'],
            ['FunnelsQuery', 'funnel'],
            ['RetentionQuery', 'retention'],
        ])('unwraps InsightVizNode wrapping %s', (sourceKind, expected) => {
            const data = {
                query: { kind: 'InsightVizNode', source: { kind: sourceKind } },
                results: formatted,
            }
            expect(inferVisualizationType(data)).toBe(expected)
        })
    })

    describe('unsupported payloads', () => {
        it.each([
            ['null', null],
            ['non-object', 'a string'],
            ['unknown query kind', { query: { kind: 'SomethingElse' }, results: 'formatted' }],
            ['wrapper with no source kind', { query: { kind: 'DataVisualizationNode' }, results: 'formatted' }],
        ])('returns null for %s', (_label, data) => {
            expect(inferVisualizationType(data)).toBeNull()
        })
    })
})
