import { MOCK_DEFAULT_USER } from '~/lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const TOOL_NAME = 'execute-sql'

// This tool's share of all MCP activity in the window: enough calls and sessions to exercise the
// call-share and session-share subtitles on the Calls and Sessions tiles with a realistic percentage.
const STATS = {
    calls: 5563,
    errors: 214,
    p50_ms: 820,
    p95_ms: 3525,
    users: 412,
    conversations: 3959,
    with_intent: 4890,
    total_calls: 13500000,
    total_conversations: 60000,
}

const DESCRIPTIONS = [
    {
        description: 'Run a ClickHouse SQL query against events, persons, and warehouse tables.',
        last_seen: '2026-06-07T10:04:00Z',
    },
    { description: 'Run a SQL query against the project.', last_seen: '2026-05-20T09:00:00Z' },
]

const DAILY_STATS = [
    { day: '2026-06-01', calls: 720, errors: 28, p50: 780, p95: 3300, users: 90, sessions: 540 },
    { day: '2026-06-02', calls: 760, errors: 31, p50: 800, p95: 3400, users: 95, sessions: 560 },
    { day: '2026-06-03', calls: 745, errors: 24, p50: 790, p95: 3350, users: 92, sessions: 555 },
    { day: '2026-06-04', calls: 810, errors: 36, p50: 850, p95: 3600, users: 101, sessions: 590 },
    { day: '2026-06-05', calls: 790, errors: 30, p50: 830, p95: 3500, users: 98, sessions: 575 },
    { day: '2026-06-06', calls: 830, errors: 33, p50: 840, p95: 3550, users: 104, sessions: 600 },
    { day: '2026-06-07', calls: 908, errors: 32, p50: 860, p95: 3700, users: 110, sessions: 620 },
]

const SAMPLE_INTENTS = [
    {
        timestamp: '2026-06-07T10:04:42Z',
        intent: 'Retry the tuned query with a shorter time range.',
        intent_source: 'context_parameter',
        harness: 'Claude Code',
    },
    {
        timestamp: '2026-06-07T09:41:10Z',
        intent: 'Break down tool errors by client to find which harness fails most.',
        intent_source: 'inferred',
        harness: 'Cursor',
    },
    {
        timestamp: '2026-06-07T08:15:00Z',
        intent: 'Corroborate homepage INP p75 with its actual seven-day sample count.',
        intent_source: 'context_parameter',
        harness: 'Claude Code',
    },
]

const NEIGHBORS_BEFORE = [
    { neighbor_tool: 'read-data-schema', co_occurrences: 2840 },
    { neighbor_tool: 'exec', co_occurrences: 610 },
]

const NEIGHBORS_AFTER = [
    { neighbor_tool: 'insight-create', co_occurrences: 1120 },
    { neighbor_tool: 'dashboard-create', co_occurrences: 340 },
]

// Session share on the "By harness" table: this tool's sessions within the harness, out of the
// harness's total sessions across all tools, spanning a high, mid, and low share.
const BY_HARNESS = [
    {
        harness: 'PostHog AI',
        total_calls: 3100,
        errors: 98,
        error_rate_pct: 3.2,
        sessions: 1200,
        harness_sessions: 1480,
    },
    { harness: 'Slack', total_calls: 1680, errors: 74, error_rate_pct: 4.4, sessions: 800, harness_sessions: 1600 },
    { harness: 'Claude Code', total_calls: 783, errors: 42, error_rate_pct: 5.4, sessions: 50, harness_sessions: 9000 },
]

const TOP_USERS = [
    {
        distinct_id: 'user-1-distinct-id',
        person_properties: JSON.stringify({ email: 'annika@example.com', name: 'Annika Hansen' }),
        calls: 890,
        errors: 22,
        error_rate_pct: 2.5,
        harnesses: ['PostHog AI', 'Claude Code'],
        last_seen: '2026-06-07T10:04:00Z',
    },
    {
        distinct_id: 'user-2-distinct-id',
        person_properties: JSON.stringify({ email: 'sven@example.com' }),
        calls: 640,
        errors: 41,
        error_rate_pct: 6.4,
        harnesses: ['Slack'],
        last_seen: '2026-06-06T18:20:00Z',
    },
]

const FAILURE_BUCKETS = [
    {
        message: 'api_5xx (HTTP 500)',
        error_type: 'api_5xx',
        error_status: '500',
        occurrences: 96,
        last_seen: '2026-06-07T09:41:10Z',
        harnesses: ['PostHog AI', 'Slack'],
    },
    {
        message: 'timeout',
        error_type: 'timeout',
        error_status: '',
        occurrences: 54,
        last_seen: '2026-06-06T22:10:00Z',
        harnesses: ['Claude Code'],
    },
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/MCP Analytics/Tool Detail',
    decorators: [
        (Story, context) =>
            mswDecorator({
                get: { '/api/users/@me/': { ...MOCK_DEFAULT_USER, theme_mode: context.globals.theme ?? 'light' } },
            })(Story, context),
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    switch (body?.query?.kind) {
                        case 'MCPToolStatsQuery':
                            return [200, { results: [STATS] }]
                        case 'MCPToolDescriptionsQuery':
                            return [200, { results: DESCRIPTIONS }]
                        case 'MCPToolDailyStatsQuery':
                            return [200, { results: DAILY_STATS }]
                        case 'MCPToolSampleIntentsQuery':
                            return [200, { results: SAMPLE_INTENTS }]
                        case 'MCPToolNeighborsQuery':
                            return [
                                200,
                                {
                                    results:
                                        body.query.neighborDirection === 'before' ? NEIGHBORS_BEFORE : NEIGHBORS_AFTER,
                                },
                            ]
                        case 'MCPHarnessBreakdownQuery':
                            return [200, { results: BY_HARNESS }]
                        case 'MCPToolTopUsersQuery':
                            return [200, { results: TOP_USERS }]
                        case 'MCPToolFailuresQuery':
                            return [200, { results: FAILURE_BUCKETS }]
                        case 'MCPToolFailureOccurrencesQuery':
                            return [200, { results: [] }]
                        default:
                            return [200, { results: [] }]
                    }
                },
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-07T12:00:00Z',
        pageUrl: urls.mcpAnalyticsTool(TOOL_NAME),
    },
}
export default meta

type Story = StoryObj<{}>

export const ToolDetail: Story = {
    parameters: { testOptions: { viewportWidths: ['narrow', 'medium', 'wide'] } },
}
