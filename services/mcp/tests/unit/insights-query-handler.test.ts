import { describe, expect, it, vi } from 'vitest'

import { queryHandler } from '@/tools/insights/query'
import { type Context, POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY } from '@/tools/types'

const filtersOverrideObject = { date_from: '-7d' }
const variablesOverrideObject = {
    '019d4838-1da4-0000-33c7-2561bf01f1c9': {
        code_name: 'eventname',
        variableId: '019d4838-1da4-0000-33c7-2561bf01f1c9',
        value: 'signed_up',
    },
}

interface InsightsCallArgs {
    insightId: string
    variables_override?: string
    filters_override?: string
}

interface MockHandles {
    context: Context
    insightsGet: ReturnType<typeof vi.fn>
    insightsQuery: ReturnType<typeof vi.fn>
}

interface QueryResult {
    query: unknown
    results: unknown
    insight: Record<string, unknown> & { url: string }
    _posthogUrl: string
    [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]?: string
}

function createContext(overrides?: { getData?: unknown; queryData?: unknown }): MockHandles {
    const insightsGet = vi.fn().mockResolvedValue({
        success: true,
        data: overrides?.getData ?? {
            id: 42,
            short_id: 'abc12345',
            query: { kind: 'HogQLQuery', query: 'select 1' },
        },
    })
    const insightsQuery = vi.fn().mockResolvedValue({
        success: true,
        data: overrides?.queryData ?? { columns: ['c'], results: [[1]] },
    })
    const context = {
        api: {
            insights: vi.fn().mockReturnValue({
                get: insightsGet,
                query: insightsQuery,
            }),
            request: vi.fn(),
            getProjectBaseUrl: vi.fn().mockReturnValue('https://us.posthog.com/project/1'),
        },
        stateManager: {
            getProjectId: vi.fn().mockResolvedValue('1'),
            getOrgID: vi.fn(),
            getRegion: vi.fn().mockResolvedValue('us'),
        },
        env: { POSTHOG_BASE_URL: 'https://us.posthog.com' },
        sessionManager: {},
        cache: {},
        getDistinctId: async () => 'test',
    } as unknown as Context

    return { context, insightsGet, insightsQuery }
}

describe('queryHandler — overrides forwarding', () => {
    it('forwards a string variables_override unchanged', async () => {
        const { context, insightsGet } = createContext()
        const variables_override = JSON.stringify(variablesOverrideObject)

        await queryHandler(context, { insightId: '42', output_format: 'json', variables_override })

        const call = insightsGet.mock.calls[0]![0] as InsightsCallArgs
        expect(call.variables_override).toBe(variables_override)
        expect(call.filters_override).toBeUndefined()
    })

    it('JSON.stringify-s an object variables_override before forwarding', async () => {
        const { context, insightsGet } = createContext()

        await queryHandler(context, {
            insightId: '42',
            output_format: 'json',
            // Cast through unknown — at runtime this is what an LLM sends; the
            // tool schema accepts it, but the inner client typing is string-only.
            variables_override: variablesOverrideObject as unknown as string,
        })

        const call = insightsGet.mock.calls[0]![0] as InsightsCallArgs
        expect(call.variables_override).toBe(JSON.stringify(variablesOverrideObject))
    })

    it('JSON.stringify-s an object filters_override before forwarding', async () => {
        const { context, insightsGet } = createContext()

        await queryHandler(context, {
            insightId: '42',
            output_format: 'json',
            filters_override: filtersOverrideObject as unknown as string,
        })

        const call = insightsGet.mock.calls[0]![0] as InsightsCallArgs
        expect(call.filters_override).toBe(JSON.stringify(filtersOverrideObject))
    })

    it('handles undefined overrides without coercing them to "undefined"', async () => {
        const { context, insightsGet } = createContext()

        await queryHandler(context, { insightId: '42', output_format: 'json' })

        const call = insightsGet.mock.calls[0]![0] as InsightsCallArgs
        expect(call.variables_override).toBeUndefined()
        expect(call.filters_override).toBeUndefined()
    })

    it('forwards mixed string + object overrides correctly', async () => {
        const { context, insightsGet } = createContext()
        const filters_override = JSON.stringify(filtersOverrideObject)

        await queryHandler(context, {
            insightId: '42',
            output_format: 'json',
            variables_override: variablesOverrideObject as unknown as string,
            filters_override,
        })

        const call = insightsGet.mock.calls[0]![0] as InsightsCallArgs
        expect(call.variables_override).toBe(JSON.stringify(variablesOverrideObject))
        expect(call.filters_override).toBe(filters_override)
    })
})

describe('queryHandler — link reflects overrides', () => {
    it('links to the bare saved insight when no overrides are passed', async () => {
        const { context } = createContext()

        const result = (await queryHandler(context, { insightId: '42', output_format: 'json' })) as QueryResult

        expect(result._posthogUrl).toBe('https://us.posthog.com/project/1/insights/abc12345')
        expect(result.insight.url).toBe('https://us.posthog.com/project/1/insights/abc12345')
    })

    it('encodes filters_override into the link query string', async () => {
        const { context } = createContext()

        const result = (await queryHandler(context, {
            insightId: '42',
            output_format: 'json',
            filters_override: filtersOverrideObject as unknown as string,
        })) as QueryResult

        const expected = `https://us.posthog.com/project/1/insights/abc12345?filters_override=${encodeURIComponent(
            JSON.stringify(filtersOverrideObject)
        )}`
        expect(result._posthogUrl).toBe(expected)
        expect(result.insight.url).toBe(expected)
    })

    it('encodes both variables_override and filters_override into the link', async () => {
        const { context } = createContext()

        const result = (await queryHandler(context, {
            insightId: '42',
            output_format: 'json',
            variables_override: variablesOverrideObject as unknown as string,
            filters_override: JSON.stringify(filtersOverrideObject),
        })) as QueryResult

        const expected = `https://us.posthog.com/project/1/insights/abc12345?variables_override=${encodeURIComponent(
            JSON.stringify(variablesOverrideObject)
        )}&filters_override=${encodeURIComponent(JSON.stringify(filtersOverrideObject))}`
        expect(result._posthogUrl).toBe(expected)
    })
})

describe('queryHandler — lean insight metadata', () => {
    it('strips the duplicated result set and heavy fields from the insight summary', async () => {
        const { context } = createContext({
            getData: {
                id: 42,
                short_id: 'abc12345',
                name: 'Signups',
                description: 'daily signups',
                query: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery' } },
                // Fields the retrieve endpoint returns that either duplicate the top-level
                // query/results or are UI/debug data the model never needs.
                result: [{ data: [1, 2], labels: ['a', 'b'] }],
                hogql: 'SELECT count() FROM events',
                created_by: { id: 1, hedgehog_config: {} },
                last_modified_by: { id: 1, hedgehog_config: {} },
                filters: { insight: 'TRENDS' },
            },
            queryData: { results: [{ data: [1, 2], labels: ['a', 'b'] }] },
        })

        const result = (await queryHandler(context, { insightId: '42', output_format: 'json' })) as QueryResult

        // Lean identifying metadata is retained.
        expect(result.insight).toMatchObject({
            id: 42,
            short_id: 'abc12345',
            name: 'Signups',
            description: 'daily signups',
        })
        // The result set lives once at the top level, not echoed back under insight.
        expect(result.insight).not.toHaveProperty('result')
        expect(result.insight).not.toHaveProperty('query')
        expect(result.insight).not.toHaveProperty('hogql')
        expect(result.insight).not.toHaveProperty('created_by')
        expect(result.insight).not.toHaveProperty('last_modified_by')
        expect(result.insight).not.toHaveProperty('filters')
    })
})

describe('queryHandler — result shape for UI rendering', () => {
    const formatted = 'c\n1'

    it('keeps structured results for a HogQL insight in optimized output', async () => {
        const { context } = createContext({
            queryData: { columns: ['c'], results: [[1]], formatted_results: formatted },
        })

        const result = (await queryHandler(context, { insightId: '42', output_format: 'optimized' })) as QueryResult

        // The UI app's structuredContent must carry the structured shape its guards expect,
        // not the formatted string — otherwise the table can't render.
        expect(result.results).toEqual({ columns: ['c'], results: [[1]] })
        expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toBe(formatted)
    })

    it('keeps structured results for a DataVisualizationNode-wrapped HogQL insight in optimized output', async () => {
        const { context } = createContext({
            getData: {
                id: 42,
                short_id: 'abc12345',
                query: { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery', query: 'select 1' } },
            },
            queryData: { columns: ['org_id', 'cost'], results: [['a', 1]], formatted_results: formatted },
        })

        const result = (await queryHandler(context, { insightId: '42', output_format: 'optimized' })) as QueryResult

        expect(result.results).toEqual({ columns: ['org_id', 'cost'], results: [['a', 1]] })
        expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toBe(formatted)
    })

    it('does not surface the formatted override in json output', async () => {
        const { context } = createContext({
            queryData: { columns: ['c'], results: [[1]], formatted_results: formatted },
        })

        const result = (await queryHandler(context, { insightId: '42', output_format: 'json' })) as QueryResult

        expect(result.results).toEqual({ columns: ['c'], results: [[1]] })
        expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toBeUndefined()
    })

    it('passes the raw results array through for trends insights', async () => {
        const trendsResults = [{ data: [1, 2], labels: ['a', 'b'] }]
        const { context } = createContext({
            getData: {
                id: 42,
                short_id: 'abc12345',
                query: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery' } },
            },
            queryData: { results: trendsResults, formatted_results: formatted },
        })

        const result = (await queryHandler(context, { insightId: '42', output_format: 'optimized' })) as QueryResult

        expect(result.results).toBe(trendsResults)
        expect(result.query).toEqual({ kind: 'TrendsQuery' })
        expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toBe(formatted)
    })

    it.each([
        ['RetentionQuery', [{ date: '2024-01-01', label: 'Day 0', values: [{ count: 10 }] }]],
        ['LifecycleQuery', [{ status: 'new', data: [1, 2], days: ['a', 'b'] }]],
        ['StickinessQuery', [{ count: 5, data: [1, 2], labels: ['1 day', '2 days'] }]],
        ['PathsQuery', [{ source: '0_a', target: '1_b', value: 3 }]],
    ])('passes the raw results array through for %s insights', async (kind, chartResults) => {
        const { context } = createContext({
            getData: {
                id: 42,
                short_id: 'abc12345',
                query: { kind: 'InsightVizNode', source: { kind } },
            },
            queryData: { results: chartResults },
        })

        const result = (await queryHandler(context, { insightId: '42', output_format: 'json' })) as QueryResult

        // Chart visualizers read the raw array; wrapping it in { columns, results } makes the
        // structural guards fall through to the table renderer and show an empty table.
        expect(result.results).toBe(chartResults)
        expect(result.query).toEqual({ kind })
    })
})
