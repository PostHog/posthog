import { ArtifactSource } from '~/queries/schema/schema-assistant-messages'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import {
    extractDashboard,
    extractDashboardCreateRevealTarget,
    extractDashboardMutationRevealTarget,
    extractErrorTrackingResponse,
    extractInsightDashboardRevealTarget,
    extractQueryResult,
    extractRecordingFilters,
    extractVisualizationArtifact,
    insightRequestIncludesDashboardTarget,
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

    describe('extractDashboardCreateRevealTarget', () => {
        it('accepts a completed dashboard-create response with a positive safe numeric id', () => {
            expect(extractDashboardCreateRevealTarget(toolMessage({ id: 7 }, {}, 'dashboard-create'))).toEqual({
                dashboardId: 7,
            })
        })

        it.each([{}, { id: 0 }, { id: -1 }, { id: 1.5 }, { id: Number.MAX_SAFE_INTEGER + 1 }, { id: '7' }])(
            'rejects malformed dashboard-create response %p',
            (rawOutput) => {
                expect(extractDashboardCreateRevealTarget(toolMessage(rawOutput, {}, 'dashboard-create'))).toBeNull()
            }
        )

        it('rejects other tool keys and unfinished calls', () => {
            expect(extractDashboardCreateRevealTarget(toolMessage({ id: 7 }, {}, 'dashboard-update'))).toBeNull()
            expect(
                extractDashboardCreateRevealTarget({
                    ...toolMessage({ id: 7 }, {}, 'dashboard-create'),
                    status: 'pending',
                })
            ).toBeNull()
        })
    })

    describe('insightRequestIncludesDashboardTarget', () => {
        it.each([
            [{ dashboards: [7] }, true],
            [{ dashboards: [0] }, true],
            [{ dashboards: [7, 8] }, true],
            [{ dashboards: '7' }, true],
            [{ dashboards: [] }, false],
            [{ dashboards: null }, false],
            [{}, false],
            [undefined, false],
        ])('reports whether %p asks for dashboard placement', (innerInput, expected) => {
            expect(insightRequestIncludesDashboardTarget(toolMessage({}, innerInput, 'insight-create'))).toBe(expected)
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

    describe('extractDashboardMutationRevealTarget', () => {
        const dashboardUrl = 'https://us.posthog.com/project/1/dashboard/7'

        it.each([
            [
                'creates a text tile',
                'dashboard-create-tile',
                { id: 7, body: '## Launch' },
                { id: 41 },
                { dashboardId: 7, tileId: 41 },
            ],
            [
                'keeps the replay alias for text-tile creation',
                'dashboard-create-text-tile',
                { id: '7', body: '## Launch' },
                { id: '41' },
                { dashboardId: 7, tileId: 41 },
            ],
            [
                'updates one text tile',
                'dashboard-update-text-tile',
                { id: 7, tile_id: 41, body: 'Updated' },
                { id: 41 },
                { dashboardId: 7, tileId: 41 },
            ],
            [
                'deletes a tile after the 204 response is enriched with a dashboard URL',
                'dashboard-delete-tile',
                { id: 7, tile_id: 41 },
                { _posthogUrl: dashboardUrl },
                { dashboardId: 7 },
            ],
            [
                'reorders tiles from an authoritative dashboard response',
                'dashboard-reorder-tiles',
                { id: 7, tile_order: [41, 42] },
                { id: 7, tiles: [{ id: 41 }, { id: 42 }] },
                { dashboardId: 7 },
            ],
            [
                'copies a tile without selecting one from the returned dashboard',
                'dashboard-tile-copy',
                { id: 7, fromDashboardId: 6, tileId: 41 },
                { id: 7, tiles: [{ id: 88 }] },
                { dashboardId: 7 },
            ],
            [
                'keeps the copy replay alias',
                'dashboards-copy-tile-create',
                { id: 7, fromDashboardId: 6, tileId: 41 },
                { id: 7, tiles: [{ id: 88 }] },
                { dashboardId: 7 },
            ],
            [
                'reveals one newly added widget',
                'dashboard-widgets-batch-add',
                { id: 7, widgets: [{ widget_type: 'session_replay_list' }] },
                { tiles: [{ id: 41 }] },
                { dashboardId: 7, tileId: 41 },
            ],
            [
                'returns dashboard-only for multiple added widgets',
                'dashboard-widgets-batch-add',
                { id: 7, widgets: [{ widget_type: 'session_replay_list' }, { widget_type: 'error_tracking_list' }] },
                { tiles: [{ id: 41 }, { id: 42 }] },
                { dashboardId: 7 },
            ],
            [
                'reveals one updated widget after its returned ID matches the request',
                'dashboard-widgets-batch-update',
                { id: 7, widgets: [{ tile_id: 41, name: 'New name' }] },
                { tiles: [{ id: 41 }] },
                { dashboardId: 7, tileId: 41 },
            ],
            [
                'keeps the batch-create replay alias',
                'dashboards-widgets-batch-create',
                { id: 7, widgets: [{ widget_type: 'session_replay_list' }] },
                { tiles: [{ id: 41 }] },
                { dashboardId: 7, tileId: 41 },
            ],
            [
                'moves a tile while retaining the authoritative source dashboard response',
                'dashboards-move-tile-create',
                { id: 7, to_dashboard: 8, tile: { id: 41 } },
                { id: 7 },
                { dashboardId: 7 },
            ],
            [
                'moves a tile through the live partial-update key',
                'dashboards-move-tile-partial-update',
                { id: 7, to_dashboard: 8, tile: { id: 41 } },
                { id: 7 },
                { dashboardId: 7 },
            ],
        ])('strictly extracts a target when it %s', (_case, resolvedKey, innerInput, rawOutput, expected) => {
            expect(extractDashboardMutationRevealTarget(toolMessage(rawOutput, innerInput, resolvedKey))).toEqual(
                expected
            )
        })

        it('accepts dashboard-update only when its response confirms the requested dashboard', () => {
            expect(
                extractDashboardMutationRevealTarget(
                    toolMessage({ id: 7, name: 'Growth' }, { id: 7 }, 'dashboard-update')
                )
            ).toEqual({ dashboardId: 7 })
            expect(
                extractDashboardMutationRevealTarget(
                    toolMessage({ id: 8, name: 'Growth' }, { id: 7 }, 'dashboard-update')
                )
            ).toBeNull()
        })

        it.each([0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1, '1.2', 'not-an-id'])(
            'rejects unsafe dashboard id %p',
            (id) => {
                expect(extractDashboardMutationRevealTarget(toolMessage({ id }, { id }, 'dashboard-update'))).toBeNull()
            }
        )

        it.each([
            [
                'a response tile with a conflicting dashboard_id',
                'dashboard-create-tile',
                { id: 41, dashboard_id: 8 },
                { id: 7 },
            ],
            [
                'a text update whose response tile disagrees with tile_id',
                'dashboard-update-text-tile',
                { id: 42 },
                { id: 7, tile_id: 41 },
            ],
            ['an empty widget batch', 'dashboard-widgets-batch-update', { tiles: [] }, { id: 7, widgets: [] }],
            [
                'a widget batch with mismatched cardinality',
                'dashboard-widgets-batch-update',
                { tiles: [{ id: 41 }] },
                { id: 7, widgets: [{ widget_type: 'session_replay_list' }, { widget_type: 'error_tracking_list' }] },
            ],
            [
                'a widget-update batch whose returned IDs do not match in order',
                'dashboard-widgets-batch-update',
                { tiles: [{ id: 42 }, { id: 41 }] },
                { id: 7, widgets: [{ tile_id: 41 }, { tile_id: 42 }] },
            ],
            [
                'malformed output',
                'dashboard-widgets-batch-update',
                'not a structured response',
                { id: 7, widgets: [{ tile_id: 41 }] },
            ],
        ])('rejects %s', (_case, resolvedKey, rawOutput, innerInput) => {
            expect(extractDashboardMutationRevealTarget(toolMessage(rawOutput, innerInput, resolvedKey))).toBeNull()
        })

        it.each([
            ['a local deployment', 'http://localhost:8010/project/1/dashboard/7'],
            ['a self-hosted deployment', 'https://posthog.example.test/project/42/dashboard/7'],
            [
                'a custom domain with query and hash',
                'https://analytics.customer.test/project/1/dashboard/7?source=mcp#highlight',
            ],
        ])('accepts a 204 tile delete from %s', (_case, url) => {
            expect(
                extractDashboardMutationRevealTarget(
                    toolMessage({ _posthogUrl: url }, { id: 7, tile_id: 41 }, 'dashboard-delete-tile')
                )
            ).toEqual({ dashboardId: 7 })
        })

        it.each([
            [undefined, 'missing enrichment'],
            [{ _posthogUrl: 'https://analytics.customer.test/project/0/dashboard/7' }, 'a zero project ID'],
            [
                { _posthogUrl: 'https://analytics.customer.test/project/9007199254740992/dashboard/7' },
                'an unsafe project ID',
            ],
            [
                { _posthogUrl: 'https://analytics.customer.test/project/1/dashboard/8' },
                'a URL for a different dashboard',
            ],
            [{ _posthogUrl: 'https://analytics.customer.test/project/1/dashboard/7/tiles' }, 'a nested route'],
            [{ _posthogUrl: 'ftp://analytics.customer.test/project/1/dashboard/7' }, 'a non-HTTP URL'],
            [{ _posthogUrl: '/project/1/dashboard/7' }, 'a relative URL'],
        ])('rejects a 204 tile delete with %s', (rawOutput, _case) => {
            expect(
                extractDashboardMutationRevealTarget(
                    toolMessage(rawOutput, { id: 7, tile_id: 41 }, 'dashboard-delete-tile')
                )
            ).toBeNull()
        })
    })

    describe('extractInsightDashboardRevealTarget', () => {
        const matchingOutput = {
            short_id: 'abc12345',
            dashboard_tiles: [{ id: 41, dashboard_id: 7, deleted: false }],
        }

        it.each(['insight-create', 'insight-update'])('extracts an authoritative tile after %s', (resolvedKey) => {
            expect(
                extractInsightDashboardRevealTarget(toolMessage(matchingOutput, { dashboards: [7] }, resolvedKey))
            ).toEqual({
                dashboardId: 7,
                tileId: 41,
                insightShortId: 'abc12345',
            })
        })

        it('accepts an active API dashboard tile whose deleted field is null', () => {
            expect(
                extractInsightDashboardRevealTarget(
                    toolMessage(
                        {
                            short_id: 'abc12345',
                            dashboard_tiles: [{ id: 41, dashboard_id: 7, deleted: null }],
                        },
                        { dashboards: [7] },
                        'insight-update'
                    )
                )
            ).toEqual({
                dashboardId: 7,
                tileId: 41,
                insightShortId: 'abc12345',
            })
        })

        it.each([
            ['missing requested dashboards', matchingOutput, {}],
            ['multiple requested dashboards', matchingOutput, { dashboards: [7, 8] }],
            ['an unsafe requested dashboard', matchingOutput, { dashboards: [0] }],
            ['a blank response short ID', { ...matchingOutput, short_id: ' ' }, { dashboards: [7] }],
            ['no response membership', { short_id: 'abc12345', dashboard_tiles: [] }, { dashboards: [7] }],
            [
                'a response membership for another dashboard',
                { ...matchingOutput, dashboard_tiles: [{ id: 41, dashboard_id: 8, deleted: false }] },
                { dashboards: [7] },
            ],
            [
                'multiple matching response tiles',
                {
                    ...matchingOutput,
                    dashboard_tiles: [
                        { id: 41, dashboard_id: 7, deleted: false },
                        { id: 42, dashboard_id: 7, deleted: false },
                    ],
                },
                { dashboards: [7] },
            ],
            [
                'a deleted matching response tile',
                { ...matchingOutput, dashboard_tiles: [{ id: 41, dashboard_id: 7, deleted: true }] },
                { dashboards: [7] },
            ],
            [
                'an unsafe returned tile ID',
                {
                    ...matchingOutput,
                    dashboard_tiles: [{ id: Number.MAX_SAFE_INTEGER + 1, dashboard_id: 7, deleted: false }],
                },
                { dashboards: [7] },
            ],
            ['malformed output', 'not a structured response', { dashboards: [7] }],
        ])('rejects %s', (_case, rawOutput, innerInput) => {
            expect(extractInsightDashboardRevealTarget(toolMessage(rawOutput, innerInput, 'insight-create'))).toBeNull()
        })
    })
})
