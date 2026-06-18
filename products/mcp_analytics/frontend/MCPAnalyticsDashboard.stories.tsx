import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const KPI_RESULTS = [
    ['2026-05-25', 320, 4100, 120, 1900, false],
    ['2026-05-26', 310, 3950, 140, 2050, false],
    ['2026-05-27', 298, 3800, 110, 1880, false],
    ['2026-06-01', 340, 4300, 150, 2100, true],
    ['2026-06-02', 355, 4500, 165, 2200, true],
    ['2026-06-03', 372, 4720, 158, 2080, true],
    ['2026-06-04', 360, 4600, 170, 2290, true],
    ['2026-06-05', 388, 4900, 182, 2150, true],
    ['2026-06-06', 401, 5100, 176, 2240, true],
    ['2026-06-07', 415, 5300, 168, 2290, true],
]

const TOOL_RESULTS = [
    ['exec', 5200, 208, 4.0, 2290],
    ['execute-sql', 1480, 144, 9.7, 3525],
    ['read-data-schema', 760, 3, 0.4, 1298],
    ['query-trends', 540, 5, 1.0, 2122],
    ['insight-create', 410, 8, 2.0, 727],
    ['dashboard-create', 260, 2, 0.8, 940],
    ['feature-flag-list', 180, 1, 0.6, 510],
    ['cohort-create', 95, 6, 6.3, 1620],
]

const SESSION_RESULTS = [
    ['0193f2a1-aaaa-bbbb-cccc-000000000001', 42, 18, 42.9, 610, 7, '2026-06-07T10:00:00Z'],
    ['0193f2a1-aaaa-bbbb-cccc-000000000002', 6, 6, 100.0, 95, 2, '2026-06-07T09:30:00Z'],
    ['0193f2a1-aaaa-bbbb-cccc-000000000003', 31, 0, 0.0, 240, 11, '2026-06-07T08:15:00Z'],
    ['0193f2a1-aaaa-bbbb-cccc-000000000004', 14, 1, 7.1, 180, 5, '2026-06-07T07:45:00Z'],
    ['0193f2a1-aaaa-bbbb-cccc-000000000005', 9, 0, 0.0, 120, 4, '2026-06-07T07:00:00Z'],
    ['0193f2a1-aaaa-bbbb-cccc-000000000006', 22, 3, 13.6, 410, 6, '2026-06-06T16:20:00Z'],
]

const HARNESS_RESULTS = [
    ['claude-code/1.2.0', 6200, 240, 820],
    ['cursor-vscode/0.42', 2100, 96, 410],
    ['codex-cli', 980, 71, 180],
    ['claude-ai', 760, 22, 240],
    ['visual studio code', 540, 12, 120],
]

const SESSION_LIST = {
    results: [
        {
            session_id: '0193f2a1-aaaa-bbbb-cccc-000000000001',
            tool_calls: 42,
            session_start: '2026-06-07T10:00:00Z',
            session_end: '2026-06-07T10:10:10Z',
            distinct_id_count: 1,
            tools_used: ['execute-sql', 'read-data-schema'],
            mcp_client_name: 'claude-code/1.2.0',
            distinct_id: 'user-1-distinct-id',
            person_email: 'annika@example.com',
            person_name: 'Annika Hansen',
            intent: 'Investigate slow dashboard queries and create a tuned insight.',
        },
        {
            session_id: '0193f2a1-aaaa-bbbb-cccc-000000000002',
            tool_calls: 6,
            session_start: '2026-06-07T09:30:00Z',
            session_end: '2026-06-07T09:31:35Z',
            distinct_id_count: 1,
            tools_used: ['query-trends'],
            mcp_client_name: 'cursor-vscode/0.42',
            distinct_id: 'user-2-distinct-id',
            person_email: '',
            person_name: '',
            intent: '',
        },
        {
            session_id: '0193f2a1-aaaa-bbbb-cccc-000000000003',
            tool_calls: 31,
            session_start: '2026-06-07T08:15:00Z',
            session_end: '2026-06-07T08:19:00Z',
            distinct_id_count: 1,
            tools_used: ['exec', 'insight-create'],
            mcp_client_name: 'codex-cli',
            distinct_id: 'user-3-distinct-id',
            person_email: 'sven@example.com',
            person_name: '',
            intent: '',
        },
    ],
    has_next: true,
}

const TOOL_CALL_LIST = {
    results: [
        {
            event_id: 'evt-1',
            timestamp: '2026-06-07T10:00:05Z',
            tool_name: 'read-data-schema',
            intent: 'Look up the events schema before writing SQL.',
            is_error: false,
            error_message: '',
            duration_ms: 420,
        },
        {
            event_id: 'evt-2',
            timestamp: '2026-06-07T10:01:10Z',
            tool_name: 'execute-sql',
            intent: 'Run the slow dashboard query with EXPLAIN.',
            is_error: false,
            error_message: '',
            duration_ms: 8125,
        },
        {
            event_id: 'evt-3',
            timestamp: '2026-06-07T10:04:42Z',
            tool_name: 'execute-sql',
            intent: 'Retry the tuned query.',
            is_error: true,
            error_message: 'Estimated query execution time is too long (max_execution_time=600)',
            duration_ms: 610000,
        },
    ],
}

const CLUSTER_SNAPSHOT = {
    status: 'ready',
    error_message: '',
    last_computed_at: '2026-06-07T06:00:00Z',
    last_computed_by_email: 'paul@posthog.com',
    computed_with: null,
    clusters: Array.from({ length: 6 }, (_, i) => ({
        id: i + 1,
        label: `Cluster ${i + 1}`,
        summary: '',
        session_count: 10 * (i + 1),
        tool_call_count: 40 * (i + 1),
        error_rate_pct: i,
        sample_session_ids: [],
        top_tools: [],
    })),
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/MCP Analytics',
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/mcp_analytics/intent_clusters/': CLUSTER_SNAPSHOT,
                '/api/environments/:team_id/mcp_analytics/sessions/': SESSION_LIST,
                '/api/environments/:team_id/mcp_analytics/sessions/:session_id/tool_calls/': TOOL_CALL_LIST,
            },
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    const query: string = body?.query?.query ?? ''
                    if (query.includes('$mcp_client_name')) {
                        return [200, { results: HARNESS_RESULTS }]
                    }
                    if (query.includes('AS session_id')) {
                        return [200, { results: SESSION_RESULTS }]
                    }
                    if (query.includes('p95_duration_ms')) {
                        return [200, { results: TOOL_RESULTS }]
                    }
                    if (query.includes('AS bucket')) {
                        return [200, { results: KPI_RESULTS }]
                    }
                    return [200, { results: [] }]
                },
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-07',
        pageUrl: urls.mcpAnalyticsDashboard(),
        featureFlags: [FEATURE_FLAGS.MCP_ANALYTICS],
    },
}
export default meta

type Story = StoryObj<{}>

export const Dashboard: Story = {}

export const Sessions: Story = {
    parameters: {
        pageUrl: urls.mcpAnalyticsSessions(),
    },
}
