import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { GENERATED_TOOLS } from '@/tools/generated/product_analytics'

// `insight-create` requires `query`; `insight-update` also requires the id.
const tools = [
    { tool: 'insight-create', base: {} },
    { tool: 'insight-update', base: { id: 1 } },
]

const parseQuery = (tool: string, base: object, query: unknown): { kind?: string; source?: unknown } => {
    const result = GENERATED_TOOLS[tool]!().schema.safeParse({ ...base, query })
    expect(result.success).toBe(true)
    return (result.data as { query: { kind?: string; source?: unknown } }).query
}

// The endpoint behind these tools (MCPInsightSerializer.validate_query) accepts a
// bare source query and wraps it before saving, but the tool schema declared only
// the two wrapper nodes, so those payloads were rejected client-side and never
// reached it. Each case here is a shape the endpoint supports.
describe('insight query shapes', () => {
    it.each(tools)('$tool keeps an InsightVizNode as sent', ({ tool, base }) => {
        const source = { kind: 'TrendsQuery', series: [] }

        expect(parseQuery(tool, base, { kind: 'InsightVizNode', source })).toEqual({
            kind: 'InsightVizNode',
            source,
        })
    })

    it.each(tools)('$tool keeps a DataVisualizationNode as sent', ({ tool, base }) => {
        const source = { kind: 'HogQLQuery', query: 'SELECT 1' }

        expect(parseQuery(tool, base, { kind: 'DataVisualizationNode', source, display: 'BoldNumber' })).toMatchObject({
            kind: 'DataVisualizationNode',
            source,
            display: 'BoldNumber',
        })
    })

    it.each(tools)('$tool wraps a bare product analytics query in an InsightVizNode', ({ tool, base }) => {
        const query = { kind: 'FunnelsQuery', series: [] }

        expect(parseQuery(tool, base, query)).toEqual({ kind: 'InsightVizNode', source: query })
    })

    it.each(tools)('$tool wraps a bare HogQL query in a DataVisualizationNode', ({ tool, base }) => {
        const query = { kind: 'HogQLQuery', query: 'SELECT 1' }

        expect(parseQuery(tool, base, query)).toMatchObject({ kind: 'DataVisualizationNode', source: query })
    })

    it.each(tools)('$tool infers the default kind for a bare HogQL query', ({ tool, base }) => {
        const query = { query: 'SELECT 1' }

        expect(parseQuery(tool, base, query)).toMatchObject({ kind: 'DataVisualizationNode', source: query })
    })

    it.each(tools)('$tool rejects a query that is not an object', ({ tool, base }) => {
        expect(GENERATED_TOOLS[tool]!().schema.safeParse({ ...base, query: 'SELECT 1' }).success).toBe(false)
    })

    it.each(tools)('$tool rejects unsupported bare query kinds', ({ tool, base }) => {
        for (const kind of ['DataTableNode', 'HogQuery', 'TotallyMadeUpNode']) {
            expect(GENERATED_TOOLS[tool]!().schema.safeParse({ ...base, query: { kind } }).success).toBe(false)
        }
    })

    it.each(tools)('$tool advertises its supported bare query objects', ({ tool }) => {
        const schema = z.toJSONSchema(GENERATED_TOOLS[tool]!().schema, { io: 'input' }) as unknown as {
            properties: { query: { anyOf: Array<{ properties?: { kind?: { const?: string; enum?: string[] } } }> } }
        }
        const queryKinds = schema.properties.query.anyOf.flatMap((branch) => {
            const kind = branch.properties?.kind
            return kind?.const ? [kind.const] : (kind?.enum ?? [])
        })

        expect(queryKinds).toContain('TrendsQuery')
        expect(queryKinds).toContain('HogQLQuery')
        expect(queryKinds).not.toContain('DataTableNode')
    })
})
