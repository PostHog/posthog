import { encode } from '@toon-format/toon'

import { ArtifactSource } from '~/queries/schema/schema-assistant-messages'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import {
    extractDashboard,
    extractDashboardMutationRevealTarget,
    extractErrorTrackingResponse,
    extractInsightDashboardRevealTarget,
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

function execMutationMessage({
    resolvedKey,
    innerInput,
    output,
    forceJson = true,
}: {
    resolvedKey: string
    innerInput: Record<string, unknown>
    output: Record<string, unknown>
    forceJson?: boolean
}): ToolCallMessage {
    return {
        ...toolMessage(forceJson ? JSON.stringify(output) : encode(output), innerInput, resolvedKey),
        rawInput: {
            command: `call ${forceJson ? '--json ' : ''}${resolvedKey} ${JSON.stringify(innerInput)}`,
        },
        innerToolName: resolvedKey,
    }
}

function dashboardResponse(id: number | string): Record<string, unknown> {
    return { id, name: 'KPIs', _posthogUrl: `https://us.posthog.com/project/1/dashboard/${id}` }
}

function widgetTile(id: number | string): Record<string, unknown> {
    return {
        id,
        insight: null,
        text: null,
        button_tile: null,
        widget: { id: 'widget-1', widget_type: 'activity_events_list', name: null, description: '', config: {} },
        layouts: {},
        filters_overrides: null,
        order: null,
        last_refresh: null,
        is_cached: false,
    }
}

describe('mcp tool adapter extractors', () => {
    describe('extractVisualizationArtifact', () => {
        it('classifies a REST insight payload with short_id as a saved insight', () => {
            const artifact = extractVisualizationArtifact(
                toolMessage({ short_id: 'abc12345', name: 'Signups', query: { kind: 'TrendsQuery' } })
            )
            expect(artifact?.envelope.source).toBe(ArtifactSource.Insight)
            expect(artifact?.envelope.artifact_id).toBe('abc12345')
            expect(artifact?.content.name).toBe('Signups')
        })

        it('classifies a query-only output as ephemeral', () => {
            const artifact = extractVisualizationArtifact(toolMessage({ query: { kind: 'TrendsQuery' }, results: [] }))
            expect(artifact?.envelope.source).toBe(ArtifactSource.State)
            expect(artifact?.envelope.artifact_id).toBe('call-1')
        })

        it('returns null when the output has no query', () => {
            expect(extractVisualizationArtifact(toolMessage({ id: 1, name: 'No query here' }))).toBeNull()
            expect(extractVisualizationArtifact(toolMessage(undefined))).toBeNull()
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

        // String rawOutput goes through the best-effort JSON/TOON parse — exec `call`s respond with
        // JSON when `--json` was passed and TOON otherwise, and the off-order format is a fallback.
        test.each([
            [
                'JSON output when the command carried --json',
                'call --json dashboard-create {}',
                '{"id": 7, "name": "Growth"}',
            ],
            ['TOON output when the command had no flag', 'call dashboard-create {}', 'id: 7\nname: Growth'],
            ['JSON output even without the flag', 'call dashboard-create {}', '{"id": 7, "name": "Growth"}'],
        ])('parses %s', (_name, command, rawOutput) => {
            const dashboard = extractDashboard({ ...toolMessage(rawOutput), rawInput: { command } })
            expect(dashboard?.id).toBe(7)
            expect(dashboard?.name).toBe('Growth')
        })

        it('extracts nothing when a string output parses as neither JSON nor TOON', () => {
            const dashboard = extractDashboard({
                ...toolMessage('created the dashboard for you'),
                rawInput: { command: 'call dashboard-create {}' },
            })
            expect(dashboard).toBeNull()
        })
    })

    describe('extractInsightDashboardRevealTarget', () => {
        it.each([
            [
                'one dashboard and a saved insight',
                { short_id: 'abc123' },
                { dashboards: [5] },
                { dashboardId: 5, insightShortId: 'abc123' },
            ],
            ['no dashboard', { short_id: 'abc123' }, { dashboards: [] }, null],
            ['multiple dashboards', { short_id: 'abc123' }, { dashboards: [5, 6] }, null],
            ['malformed output', undefined, { dashboards: [5] }, null],
        ])('returns %s only when one dashboard is safe to reveal', (_name, rawOutput, innerInput, expected) => {
            expect(extractInsightDashboardRevealTarget(toolMessage(rawOutput, innerInput, 'insight-create'))).toEqual(
                expected
            )
        })
    })

    describe('extractDashboardMutationRevealTarget', () => {
        it.each([
            ['dashboard-create-text-tile', { id: 101 }, { id: 5 }, { dashboardId: 5, tileId: 101 }, true],
            [
                'dashboard-update-text-tile',
                { id: 102 },
                { id: 5, tile_id: 102 },
                { dashboardId: 5, tileId: 102 },
                false,
            ],
            [
                'dashboard-widgets-batch-add',
                { tiles: [widgetTile(103)] },
                { id: 5, widgets: [{ widget_type: 'activity_events_list', config: {} }] },
                { dashboardId: 5, tileId: 103 },
                true,
            ],
            [
                'dashboard-widgets-batch-update',
                { tiles: [widgetTile(104)] },
                { id: 5, widgets: [{ tile_id: 104, widget_type: 'activity_events_list', name: 'Recent events' }] },
                { dashboardId: 5, tileId: 104 },
                false,
            ],
            [
                'dashboard-update',
                dashboardResponse(5),
                { id: 5, tiles: [{ id: 105, layouts: {} }] },
                { dashboardId: 5, tileId: 105 },
                true,
            ],
            [
                'dashboard-tile-copy',
                dashboardResponse(5),
                { id: 5, fromDashboardId: 4, tileId: 106 },
                { dashboardId: 5 },
                false,
            ],
            ['dashboard-reorder-tiles', dashboardResponse(5), { id: 5, tile_order: [106] }, { dashboardId: 5 }, true],
            [
                'dashboard-delete-tile',
                { _posthogUrl: 'https://us.posthog.com/project/1/dashboard/5' },
                { id: 5, tile_id: 106 },
                { dashboardId: 5 },
                false,
            ],
            [
                'dashboards-move-tile-partial-update',
                dashboardResponse(5),
                { id: 5, to_dashboard: 6, tile: { id: 106 } },
                { dashboardId: 6, tileId: 106 },
                true,
            ],
        ])('extracts the schema-specific target for %s', (resolvedKey, output, innerInput, expected, forceJson) => {
            expect(
                extractDashboardMutationRevealTarget(
                    execMutationMessage({ resolvedKey, innerInput, output, forceJson })
                )
            ).toEqual(expected)
        })

        it.each([
            [
                'several created tiles',
                'dashboard-widgets-batch-add',
                { tiles: [widgetTile(101), widgetTile(102)] },
                {
                    id: 5,
                    widgets: [
                        { widget_type: 'activity_events_list', config: {} },
                        { widget_type: 'logs_list', config: {} },
                    ],
                },
            ],
            [
                'several updated tiles',
                'dashboard-widgets-batch-update',
                { tiles: [widgetTile(101), widgetTile(102)] },
                { id: 5, widgets: [{ tile_id: 101 }, { tile_id: 102 }] },
            ],
            [
                'several dashboard-update tiles',
                'dashboard-update',
                dashboardResponse(5),
                { id: 5, tiles: [{ id: 101 }, { id: 102 }] },
            ],
        ])('does not select a tile when %s are affected', (_name, resolvedKey, output, innerInput) => {
            expect(
                extractDashboardMutationRevealTarget(execMutationMessage({ resolvedKey, innerInput, output }))
            ).toEqual({
                dashboardId: 5,
            })
        })

        it.each([
            ['text tile without its response tile id', 'dashboard-create-text-tile', {}, { id: 5 }],
            ['batch add without its tiles response', 'dashboard-widgets-batch-add', {}, { id: 5 }],
            ['batch update with an incomplete tile', 'dashboard-widgets-batch-update', { tiles: [{}] }, { id: 5 }],
            ['dashboard update without its Dashboard response id', 'dashboard-update', { name: 'KPIs' }, { id: 5 }],
            ['copy without its Dashboard response id', 'dashboard-tile-copy', { name: 'KPIs' }, { id: 5 }],
            ['reorder with a zero Dashboard response id', 'dashboard-reorder-tiles', dashboardResponse(0), { id: 5 }],
            [
                'move with a fractional source Dashboard response id',
                'dashboards-move-tile-partial-update',
                dashboardResponse(5.5),
                { id: 5, to_dashboard: 6, tile: { id: 106 } },
            ],
            [
                'delete with a fabricated Dashboard id instead of its enriched 204 output',
                'dashboard-delete-tile',
                { id: 5, name: 'KPIs' },
                { id: 5, tile_id: 106 },
            ],
            ['delete without the enriched 204 URL', 'dashboard-delete-tile', {}, { id: 5, tile_id: 106 }],
            ['negative numeric-string input id', 'dashboard-reorder-tiles', dashboardResponse(5), { id: '-5' }],
            ['zero numeric-string input id', 'dashboard-reorder-tiles', dashboardResponse(5), { id: '0' }],
            ['fractional numeric-string input id', 'dashboard-reorder-tiles', dashboardResponse(5), { id: '5.5' }],
        ])(
            'rejects %s even when input contains a usable dashboard target',
            (_name, resolvedKey, output, innerInput) => {
                expect(
                    extractDashboardMutationRevealTarget(execMutationMessage({ resolvedKey, innerInput, output }))
                ).toBeNull()
            }
        )

        it('normalizes safe numeric-string dashboard and tile IDs', () => {
            expect(
                extractDashboardMutationRevealTarget(
                    execMutationMessage({
                        resolvedKey: 'dashboard-create-text-tile',
                        innerInput: { id: '5' },
                        output: { id: '101' },
                    })
                )
            ).toEqual({ dashboardId: 5, tileId: 101 })
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

    describe('extractErrorTrackingResponse', () => {
        it('accepts outputs carrying known search-response fields', () => {
            const response = { status: 'active', search_query: 'TypeError', issues: [] }
            expect(extractErrorTrackingResponse(toolMessage(response))).toBe(response)
        })

        it('rejects outputs without any known field', () => {
            expect(extractErrorTrackingResponse(toolMessage({ results: [{ id: 'issue-1' }] }))).toBeNull()
            expect(extractErrorTrackingResponse(toolMessage(undefined))).toBeNull()
        })
    })

    describe('extractQueryResult', () => {
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

        it('uses the tool input when optimized streamed results omit structured raw output', () => {
            const result = extractQueryResult(
                toolMessage(undefined, { kind: 'TrendsQuery', series: [], output_format: 'optimized' }, 'query-trends')
            )
            expect(result?.content.query).toEqual({ kind: 'TrendsQuery', series: [] })
            expect(result?.url).toBeNull()
        })

        it('infers the query kind from the wrapper tool key when the input omits kind', () => {
            const result = extractQueryResult(toolMessage(undefined, { series: [] }, 'query-trends'))
            expect(result?.content.query).toEqual({ kind: 'TrendsQuery', series: [] })
        })

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
        })
    })
})
