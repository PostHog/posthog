import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/product_analytics'

const BARE_TRENDS_QUERY = {
    kind: 'TrendsQuery',
    series: [{ kind: 'EventsNode', event: '$pageview', name: '$pageview' }],
    dateRange: { date_from: '-7d' },
    interval: 'day',
}

// Every shape `MCPInsightSerializer.validate_query` normalizes and saves. The bare ones are
// wrapped server-side, so the tool boundary has to pass them through rather than reject them.
const acceptedQueries = [
    {
        shape: 'wrapped InsightVizNode',
        query: { kind: 'InsightVizNode', source: BARE_TRENDS_QUERY },
    },
    {
        shape: 'wrapped DataVisualizationNode',
        query: { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery', query: 'select 1' } },
    },
    { shape: 'bare TrendsQuery', query: BARE_TRENDS_QUERY },
    { shape: 'bare HogQLQuery', query: { kind: 'HogQLQuery', query: 'select 1' } },
    {
        shape: 'bare WebStatsTableQuery',
        query: { kind: 'WebStatsTableQuery', breakdownBy: 'Page', properties: [], dateRange: { date_from: '-7d' } },
    },
]

const tools = [
    { tool: 'insight-create', base: {} },
    { tool: 'insight-update', base: { id: 1 } },
]

const cases = tools.flatMap(({ tool, base }) => acceptedQueries.map((accepted) => ({ tool, base, ...accepted })))

describe('insight query shapes', () => {
    it.each(cases)('$tool accepts a $shape', ({ tool, base, query }) => {
        const { schema } = GENERATED_TOOLS[tool]!()

        expect(schema.safeParse({ ...base, query }).success).toBe(true)
    })

    it.each(tools)('$tool sends a bare query on to the endpoint whole', ({ tool, base }) => {
        const { schema } = GENERATED_TOOLS[tool]!()

        const result = schema.safeParse({ ...base, query: BARE_TRENDS_QUERY })

        // The bare branches carry an index signature so the query keeps its body. Without it zod
        // strips every key it does not declare, and the insight saves as an empty TrendsQuery.
        expect(result.success).toBe(true)
        expect((result.data as { query: unknown }).query).toEqual(BARE_TRENDS_QUERY)
    })

    it.each(tools)('$tool rejects a query kind the endpoint refuses to save', ({ tool, base }) => {
        const { schema } = GENERATED_TOOLS[tool]!()

        const query = { kind: 'ErrorTrackingQuery', dateRange: { date_from: '-7d' }, orderBy: 'last_seen' }

        expect(schema.safeParse({ ...base, query }).success).toBe(false)
    })
})
