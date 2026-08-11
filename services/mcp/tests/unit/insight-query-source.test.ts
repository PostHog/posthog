import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/product_analytics'

const schema = GENERATED_TOOLS['insight-create']!().schema

const parse = (query: unknown): boolean => schema.safeParse({ name: 'Test insight', query }).success

// `kind` on both node types carries a default, so an untyped `source` on either one
// turns the whole union into a catch-all that forwards anything to the API.
describe('insight-create query source', () => {
    it.each([
        ['trends, node kind supplied', { kind: 'InsightVizNode', source: { kind: 'TrendsQuery', series: [] } }],
        ['trends, node kind inferred', { source: { kind: 'TrendsQuery', series: [] } }],
        ['sql', { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery', query: 'select 1' } }],
    ])('accepts %s', (_label, query) => {
        expect(parse(query)).toBe(true)
    })

    it.each([
        ['a source kind that is not an insight query', { source: { kind: 'NotAQuery' } }],
        ['a source with no kind at all', { source: { anything: true } }],
        ['a trends source missing its required series', { source: { kind: 'TrendsQuery' } }],
    ])('rejects %s', (_label, query) => {
        expect(parse(query)).toBe(false)
    })
})
