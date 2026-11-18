import { ArtifactSource } from '~/queries/schema/schema-assistant-messages'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import {
    extractDashboard,
    extractQueryResult,
    extractRecordingFilters,
    extractVisualizationArtifact,
} from './extractors'

function toolMessage(
    rawOutput: unknown,
    innerInput?: Record<string, unknown>,
    resolvedKey = 'test-tool'
): ToolCallMessage {
    return {
        id: 'call-1',
        resolvedKey,
        rawServerName: 'posthog',
        rawToolName: 'mcp__posthog__exec',
        rawInput: {},
        innerInput,
        rawOutput,
        content: [],
        status: 'completed',
    }
}

describe('mcp tool adapter extractors', () => {
    describe('extractVisualizationArtifact', () => {
        const savedInsight = { short_id: 'abc12345', name: 'Signups', query: { kind: 'TrendsQuery' } }

        it.each([
            ['direct payload', savedInsight],
            [
                'MCP structured content',
                {
                    structuredContent: savedInsight,
                    content: [{ type: 'text', text: '{"query":{"kind":"FunnelsQuery"}}' }],
                    isError: false,
                },
            ],
            [
                'MCP metadata takes precedence over formatted and structured content',
                {
                    _meta: { 'com.posthog.mcp/app_data': savedInsight },
                    structuredContent: { query: { kind: 'FunnelsQuery' } },
                    content: [{ type: 'text', text: 'query: {\n  "kind": "TrendsQuery"\n}' }],
                    isError: false,
                },
            ],
        ])('classifies a saved insight from %s', (_format, rawOutput) => {
            const artifact = extractVisualizationArtifact(toolMessage(rawOutput))
            expect(artifact?.envelope.source).toBe(ArtifactSource.Insight)
            expect(artifact?.envelope.artifact_id).toBe('abc12345')
            expect(artifact?.content.name).toBe('Signups')
            expect(artifact?.content.query).toEqual(savedInsight.query)
        })

        it('classifies a query-only output as ephemeral', () => {
            const artifact = extractVisualizationArtifact(toolMessage({ query: { kind: 'TrendsQuery' }, results: [] }))
            expect(artifact?.envelope.source).toBe(ArtifactSource.State)
            expect(artifact?.envelope.artifact_id).toBe('call-1')
        })

        it.each([
            undefined,
            { id: 1, name: 'No query here' },
            { content: [] },
            { content: [null, { type: 'image', data: 'unused', mimeType: 'image/png' }] },
            { content: [{ type: 'text', text: 'No insight found' }] },
            { structuredContent: savedInsight, isError: true },
            { _meta: { 'com.posthog.mcp/app_data': savedInsight }, isError: true },
            { _meta: { 'com.posthog.mcp/app_data': [] } },
            { content: [{ type: 'text', text: JSON.stringify(savedInsight) }] },
            { content: [{ type: 'text', text: 'query: {\n  "kind": "TrendsQuery"\n}' }] },
        ])('returns null for missing, malformed, or failed insight output: %j', (rawOutput) => {
            expect(extractVisualizationArtifact(toolMessage(rawOutput))).toBeNull()
        })
    })

    describe('extractDashboard', () => {
        it('reads id and the _posthogUrl enrichment from the REST payload', () => {
            const dashboard = extractDashboard(
                toolMessage({ id: 42, name: 'KPIs', _posthogUrl: 'https://us.posthog.com/project/1/dashboard/42' })
            )
            expect(dashboard).toEqual({
                id: 42,
                name: 'KPIs',
                url: 'https://us.posthog.com/project/1/dashboard/42',
            })
        })

        it('falls back to legacy dashboard_id / url fields and the input name', () => {
            const dashboard = extractDashboard(
                toolMessage({ dashboard_id: '7', url: '/dashboard/7' }, { name: 'From input' })
            )
            expect(dashboard).toEqual({ id: '7', name: 'From input', url: '/dashboard/7' })
        })

        test.each([
            [
                'JSON output when the command carried --json',
                'call --json dashboard-create {}',
                '{"id": 7, "name": "Growth"}',
            ],
            ['TOON output when the command had no flag', 'call dashboard-create {}', 'id: 7\nname: Growth'],
            ['JSON output even without the flag', 'call dashboard-create {}', '{"id": 7, "name": "Growth"}'],
        ])('leaves legacy %s to the generic card', (_name, command, rawOutput) => {
            const dashboard = extractDashboard({ ...toolMessage(rawOutput), rawInput: { command } })
            expect(dashboard).toBeNull()
        })

        it('extracts nothing when a string output parses as neither JSON nor TOON', () => {
            const dashboard = extractDashboard({
                ...toolMessage('created the dashboard for you'),
                rawInput: { command: 'call dashboard-create {}' },
            })
            expect(dashboard).toBeNull()
        })
    })

    describe('extractRecordingFilters', () => {
        it('maps the query-wrapper output back to universal filters', () => {
            const filters = extractRecordingFilters(
                toolMessage({
                    query: {
                        kind: 'RecordingsQuery',
                        date_from: '-7d',
                        filter_test_accounts: true,
                        properties: [{ type: 'person', key: 'email', operator: 'icontains', value: 'posthog' }],
                    },
                    results: [],
                    _posthogUrl: 'https://us.posthog.com/project/1/replay',
                })
            )
            expect(filters?.date_from).toBe('-7d')
            expect(filters?.filter_test_accounts).toBe(true)
            expect(filters?.filter_group.values).toEqual([
                {
                    type: 'AND',
                    values: [{ type: 'person', key: 'email', operator: 'icontains', value: 'posthog' }],
                },
            ])
        })

        it('passes through a ready-made universal filters object', () => {
            const universal = {
                date_from: '-3d',
                duration: [],
                filter_group: { type: 'AND', values: [] },
            }
            expect(extractRecordingFilters(toolMessage({ filters: universal }))).toBe(universal)
        })

        it('returns null for outputs carrying neither shape', () => {
            expect(extractRecordingFilters(toolMessage({ results: [] }))).toBeNull()
            expect(extractRecordingFilters(toolMessage({ filters: { some: 'garbage' } }))).toBeNull()
            expect(extractRecordingFilters(toolMessage(undefined))).toBeNull()
        })
    })

    describe('extractQueryResult', () => {
        it.each([
            { kind: 'HogQLQuery', query: 'SELECT 1' },
            { kind: 'HogQLQuery', query: 'SELECT 1', connectionId: 'example-connection', sendRawQuery: true },
            {
                kind: 'HogQLQuery',
                query: 'SELECT {variables.org}',
                variables: { 'example-variable': { variableId: 'example-variable', code_name: 'org' } },
            },
        ])('renders the executed SQL query with its resolved settings: %j', (query) => {
            const result = extractQueryResult(
                toolMessage(
                    {
                        content: [{ type: 'text', text: '1' }],
                        _meta: { 'com.posthog.mcp/app_data': { query } },
                    },
                    { query: `${query.query};` },
                    'execute-sql'
                )
            )
            expect(result?.content.query).toEqual(query)
            expect(result?.url).toBeNull()
        })

        it.each<Partial<ToolCallMessage>>([
            { status: 'pending' },
            { status: 'in_progress' },
            { status: 'failed' },
            { rawOutput: { isError: true } },
            { rawOutput: { content: [{ type: 'text', text: '1' }] } },
            { rawOutput: { _meta: { 'com.posthog.mcp/app_data': { query: 'SELECT 1' } } } },
            { rawOutput: { _meta: { 'com.posthog.mcp/app_data': { query: { kind: 'HogQLQuery' } } } } },
            { rawOutput: undefined },
        ])('falls back for incomplete SQL calls or missing query metadata: %j', (overrides) => {
            expect(
                extractQueryResult({
                    ...toolMessage(
                        { _meta: { 'com.posthog.mcp/app_data': { query: { kind: 'HogQLQuery', query: 'SELECT 1' } } } },
                        { query: 'SELECT {variables.org}' },
                        'execute-sql'
                    ),
                    ...overrides,
                })
            ).toBeNull()
        })

        it.each([
            { kind: 'TrendsQuery', series: [] },
            { kind: 'HogQLQuery', query: 'SELECT 1' },
            { kind: 'InsightVizNode', source: { kind: 'StickinessQuery', series: [] } },
            { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery', query: 'SELECT 1' } },
            { kind: 'DataTableNode', source: { kind: 'EventsQuery', select: ['*'] } },
        ])('preserves a saved insight query ($kind) and its overridden link', (query) => {
            const url = '/project/1/insights/example?variables_override=%7B%7D'
            const result = extractQueryResult(
                toolMessage(
                    {
                        content: [{ type: 'text', text: 'Date|count\n2026-01-01|3' }],
                        _meta: {
                            'com.posthog.mcp/app_data': {
                                query,
                                results: [],
                                insight: {
                                    name: 'Synthetic insight',
                                    description: 'Saved query',
                                    url: '/insights/example',
                                },
                                _posthogUrl: url,
                            },
                        },
                    },
                    { insightId: 'example' },
                    'insight-query'
                )
            )
            expect(result?.content.query).toEqual(query)
            expect(result?.content.name).toEqual('Synthetic insight')
            expect(result?.url).toEqual(url)
        })

        it.each(['TrendsQuery', 'FunnelsQuery', 'RetentionQuery', 'StickinessQuery', 'PathsQuery', 'LifecycleQuery'])(
            'passes a bare %s through for InsightVizNode wrapping downstream',
            (kind) => {
                const result = extractQueryResult(
                    toolMessage({
                        query: { kind, series: [] },
                        results: [],
                        _posthogUrl: 'https://us.posthog.com/insights/new',
                    })
                )
                expect(result?.content.query).toEqual({ kind, series: [] })
                expect(result?.url).toBe('https://us.posthog.com/insights/new')
            }
        )

        it('wraps a TracesQuery in a DataTableNode', () => {
            const result = extractQueryResult(toolMessage({ query: { kind: 'TracesQuery' }, results: [] }))
            expect(result?.content.query).toEqual({ kind: 'DataTableNode', source: { kind: 'TracesQuery' } })
            expect(result?.url).toBeNull()
        })

        it.each([{ kind: 'TrendsQuery', series: [] }, { series: [] }])(
            'falls back when the executed query is absent, even if input could supply it: %j',
            (input) => {
                expect(extractQueryResult(toolMessage(undefined, input, 'query-trends'))).toBeNull()
            }
        )

        it('wraps the actors wrapper output (ActorsQuery envelope) untouched in a DataTableNode', () => {
            const actorsQuery = {
                kind: 'ActorsQuery',
                source: { kind: 'InsightActorsQuery', source: { kind: 'TrendsQuery' } },
                select: ['actor'],
            }
            const result = extractQueryResult(
                toolMessage({ query: actorsQuery, results: { columns: [], results: [] } })
            )
            expect(result?.content.query).toEqual({ kind: 'DataTableNode', source: actorsQuery })
        })

        it('wraps a bare InsightActorsQuery in an ActorsQuery before the DataTableNode', () => {
            const insightActors = { kind: 'InsightActorsQuery', source: { kind: 'TrendsQuery' } }
            const result = extractQueryResult(toolMessage({ query: insightActors }))
            expect(result?.content.query).toEqual({
                kind: 'DataTableNode',
                source: { kind: 'ActorsQuery', source: insightActors, select: ['actor'] },
            })
        })

        it('returns null for kinds without an inline renderer or malformed outputs', () => {
            expect(extractQueryResult(toolMessage({ query: { kind: 'TraceQuery', traceId: 't1' } }))).toBeNull()
            expect(extractQueryResult(toolMessage({ results: [] }))).toBeNull()
            expect(extractQueryResult(toolMessage({ query: 'not-an-object' }))).toBeNull()
            expect(extractQueryResult(toolMessage(undefined))).toBeNull()
            expect(extractQueryResult(toolMessage(undefined, { insightId: 'example' }, 'insight-query'))).toBeNull()
            expect(extractQueryResult(toolMessage({ query: { kind: 'InsightVizNode' } }))).toBeNull()
            expect(extractQueryResult(toolMessage({ query: { kind: 'DataVisualizationNode' } }))).toBeNull()
            expect(extractQueryResult(toolMessage({ query: { kind: 'DataTableNode' } }))).toBeNull()
        })
    })
})
