import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
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

// One [day, calls, errors] table drives both time-series charts so they agree with
// each other and with KPI_RESULTS' daily tool_calls/errors by construction.
const DAILY_TOTALS: [string, number, number][] = [
    ['2026-05-31', 4200, 145],
    ['2026-06-01', 4300, 150],
    ['2026-06-02', 4500, 165],
    ['2026-06-03', 4720, 158],
    ['2026-06-04', 4600, 170],
    ['2026-06-05', 4900, 182],
    ['2026-06-06', 5100, 176],
    ['2026-06-07', 5300, 168],
]

const ACTIVITY_RESULTS = DAILY_TOTALS.map(([day, calls, errors]) => [day, calls - errors, errors])

const TOOL_DAILY_SHARES: [string, number][] = [
    ['exec', 0.58],
    ['execute-sql', 0.17],
    ['read-data-schema', 0.085],
    ['query-trends', 0.06],
    ['insight-create', 0.046],
    ['dashboard-create', 0.029],
]

const TOOL_DAILY_RESULTS = DAILY_TOTALS.flatMap(([day, calls]) =>
    TOOL_DAILY_SHARES.map(([tool, share]) => [day, tool, Math.round(calls * share)])
)

const SESSION_RESULTS = [
    ['0193f2a1-aaaa-bbbb-cccc-000000000001', 42, 18, 42.9, 610, 7, '2026-06-07T10:00:00Z'],
    ['0193f2a1-aaaa-bbbb-cccc-000000000002', 6, 6, 100.0, 95, 2, '2026-06-07T09:30:00Z'],
    ['0193f2a1-aaaa-bbbb-cccc-000000000003', 31, 0, 0.0, 240, 11, '2026-06-07T08:15:00Z'],
    ['0193f2a1-aaaa-bbbb-cccc-000000000004', 14, 1, 7.1, 180, 5, '2026-06-07T07:45:00Z'],
    ['0193f2a1-aaaa-bbbb-cccc-000000000005', 9, 0, 0.0, 120, 4, '2026-06-07T07:00:00Z'],
    ['0193f2a1-aaaa-bbbb-cccc-000000000006', 22, 3, 13.6, 410, 6, '2026-06-06T16:20:00Z'],
]

// MCPHarnessBreakdownQuery returns already-labelled rows (the runner resolves the
// harness server-side), so these are customer labels, not raw client strings.
const HARNESS_RESULTS = [
    { harness: 'Claude Code', total_calls: 6200, errors: 240, error_rate_pct: 3.9, sessions: 820 },
    { harness: 'Cursor', total_calls: 2100, errors: 96, error_rate_pct: 4.6, sessions: 410 },
    { harness: 'OpenAI Codex', total_calls: 980, errors: 71, error_rate_pct: 7.2, sessions: 180 },
    { harness: 'Claude.ai', total_calls: 760, errors: 22, error_rate_pct: 2.9, sessions: 240 },
    { harness: 'VS Code', total_calls: 540, errors: 12, error_rate_pct: 2.2, sessions: 120 },
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

// Tool quality tab — one row per tool: tool, total_calls, errors, error_rate_pct,
// p50, p95, p99, users, sessions, first_seen, last_seen.
type ToolQualityStoryRow = [string, number, number, number, number, number, number, number, number, string, string]

const TOOL_QUALITY_ROWS: ToolQualityStoryRow[] = [
    ['execute-sql', 1480, 144, 9.7, 820, 3525, 9800, 210, 540, '2026-05-08T09:00:00Z', '2026-06-07T10:04:00Z'],
    ['read-data-schema', 760, 3, 0.4, 180, 1298, 2600, 160, 410, '2026-05-08T08:00:00Z', '2026-06-07T10:00:00Z'],
    ['query-trends', 540, 5, 1.0, 410, 2122, 4100, 120, 300, '2026-05-09T11:00:00Z', '2026-06-07T09:45:00Z'],
    ['insight-create', 410, 8, 2.0, 260, 727, 1500, 95, 210, '2026-05-10T14:00:00Z', '2026-06-06T18:00:00Z'],
    ['dashboard-create', 260, 2, 0.8, 300, 940, 1800, 70, 150, '2026-05-11T10:00:00Z', '2026-06-06T16:00:00Z'],
    ['cohort-create', 95, 6, 6.3, 480, 1620, 3100, 40, 80, '2026-05-12T13:00:00Z', '2026-06-05T12:00:00Z'],
    ...Array.from(
        { length: 54 },
        (_, index): ToolQualityStoryRow => [
            `workflow-action-${String(index + 1).padStart(2, '0')}`,
            90 - index,
            index % 7 === 0 ? 1 : 0,
            index % 7 === 0 ? 1.5 : 0,
            120 + index * 5,
            480 + index * 10,
            900 + index * 20,
            30 + index,
            40 + index,
            '2026-05-12T13:00:00Z',
            '2026-06-05T12:00:00Z',
        ]
    ),
]

// Tool quality daily stats (selected/aggregate): day, calls, errors, p50, p95, p99.
const DAILY_STATS = [
    ['2026-06-01', 480, 22, 800, 3400, 9200],
    ['2026-06-02', 510, 31, 840, 3520, 9600],
    ['2026-06-03', 495, 18, 790, 3300, 8900],
    ['2026-06-04', 530, 40, 870, 3700, 10200],
    ['2026-06-05', 560, 27, 810, 3450, 9400],
    ['2026-06-06', 540, 19, 800, 3380, 9100],
    ['2026-06-07', 575, 33, 830, 3500, 9700],
]

const CATEGORY_LIST = [['Data exploration'], ['Insights'], ['Dashboards'], ['Cohorts']]

// One category per tool in the clustering fixture. Deliberately selective: `SQL` and
// `Insights` each cover two of the three clusters, so picking one visibly narrows the list
// rather than leaving it whole.
const TOOL_CATEGORY_MAP = [
    ['execute-sql', 'SQL'],
    ['insight-create', 'Insights'],
    ['query-trends', 'Product analytics'],
    ['read-data-schema', 'Data schema'],
]

const CATEGORY_COUNTS = [
    ['Data exploration', 2240],
    ['Insights', 950],
    ['Dashboards', 260],
    ['Cohorts', 95],
    ['', 410],
]

// Scoped to $mcp_tool_call via eventNames — these populate the property-filter picker.
const MCP_PROPERTY_DEFINITIONS = {
    count: 5,
    results: [
        { id: 'tool', name: '$mcp_tool_name', property_type: 'String', is_seen_on_filtered_events: true },
        { id: 'err', name: '$mcp_is_error', property_type: 'Boolean', is_seen_on_filtered_events: true },
        { id: 'client', name: '$mcp_client_name', property_type: 'String', is_seen_on_filtered_events: true },
        { id: 'session', name: '$mcp_session_id', property_type: 'String', is_seen_on_filtered_events: true },
        { id: 'duration', name: '$mcp_duration_ms', property_type: 'Numeric', is_seen_on_filtered_events: true },
    ],
}

const MCP_FEATURE_FLAG_DEFINITIONS = {
    count: 1,
    results: [
        {
            id: 'flag',
            name: '$feature/mcp-new-thing',
            property_type: 'String',
            is_seen_on_filtered_events: true,
        },
    ],
}

// Intent clustering tab. Matches MCPIntentClusterSnapshotApi — clusters carry a
// tool_distribution (heatmap), sample_intents, routing_entropy (badge variants),
// and a Sankey journey. The three entropy bands exercise every badge colour.
const CLUSTER_SNAPSHOT = {
    status: 'idle',
    error_message: '',
    last_computed_at: '2026-06-07T06:00:00Z',
    last_computed_by_email: 'paul@posthog.com',
    computed_with: {
        distance_threshold: 0.35,
        embedding_model: 'text-embedding-3-small',
        n_intents: 412,
        n_clusters: 3,
    },
    clusters: [
        {
            id: 1,
            label: 'Investigate slow dashboard queries and tune them',
            intent_count: 64,
            session_count: 48,
            call_count: 1820,
            error_count: 96,
            error_rate_pct: 5.3,
            routing_entropy: 0.24,
            tool_distribution: [
                { tool: 'execute-sql', count: 1480, pct: 81.3, errors: 92, error_rate_pct: 6.2 },
                { tool: 'read-data-schema', count: 260, pct: 14.3, errors: 2, error_rate_pct: 0.8 },
                { tool: 'query-trends', count: 80, pct: 4.4, errors: 2, error_rate_pct: 2.5 },
            ],
            sample_intents: [
                'Find why the revenue dashboard takes 30s to load and rewrite the query.',
                'EXPLAIN the slow funnel query and add an index hint.',
                'Profile the top 5 slowest insights this week.',
            ],
            journey: {
                total_sessions: 48,
                paths: [
                    {
                        steps: ['read-data-schema', 'execute-sql', 'execute-sql', null],
                        outcome: 'completed',
                        count: 26,
                    },
                    { steps: ['execute-sql', 'execute-sql', null, null], outcome: 'error', count: 14 },
                    { steps: ['read-data-schema', 'query-trends', null, null], outcome: 'completed', count: 8 },
                ],
                leak: { steps: ['execute-sql', 'execute-sql', null, null], outcome: 'error', count: 14 },
            },
        },
        {
            id: 2,
            label: 'Create and tweak insights from natural language',
            intent_count: 41,
            session_count: 33,
            call_count: 690,
            error_count: 14,
            error_rate_pct: 2.0,
            routing_entropy: 0.55,
            tool_distribution: [
                { tool: 'insight-create', count: 320, pct: 46.4, errors: 8, error_rate_pct: 2.5 },
                { tool: 'query-trends', count: 240, pct: 34.8, errors: 4, error_rate_pct: 1.7 },
                { tool: 'read-data-schema', count: 130, pct: 18.8, errors: 2, error_rate_pct: 1.5 },
            ],
            sample_intents: [
                'Build a weekly active users trend split by plan.',
                'Make a funnel from signup to first insight created.',
            ],
            journey: {
                total_sessions: 33,
                paths: [
                    {
                        steps: ['read-data-schema', 'query-trends', 'insight-create', null],
                        outcome: 'completed',
                        count: 21,
                    },
                    { steps: ['insight-create', null, null, null], outcome: 'completed', count: 9 },
                ],
                leak: null,
            },
        },
        {
            id: 3,
            label: 'Explore the event schema and available properties',
            intent_count: 29,
            session_count: 22,
            call_count: 410,
            error_count: 3,
            error_rate_pct: 0.7,
            routing_entropy: 0.82,
            tool_distribution: [
                { tool: 'read-data-schema', count: 150, pct: 36.6, errors: 1, error_rate_pct: 0.7 },
                { tool: 'execute-sql', count: 120, pct: 29.3, errors: 1, error_rate_pct: 0.8 },
                { tool: 'query-trends', count: 90, pct: 22.0, errors: 1, error_rate_pct: 1.1 },
                { tool: 'insight-create', count: 50, pct: 12.2, errors: 0, error_rate_pct: 0.0 },
            ],
            sample_intents: [
                'What properties does the $pageview event have?',
                'List all custom events captured in the last 30 days.',
            ],
            journey: null,
            // Only this cluster carries recovery data, so the story covers both the section
            // rendering and the other clusters, which stand in for snapshots predating it.
            switches: [
                { from_tool: 'query-trends', to_tool: 'execute-sql', count: 6 },
                { from_tool: 'insight-create', to_tool: 'query-trends', count: 2 },
            ],
            self_retries: [{ tool: 'read-data-schema', count: 4 }],
        },
    ],
    tools: [
        {
            tool: 'execute-sql',
            call_count: 1720,
            error_count: 94,
            session_count: 61,
            contested_score: 0.31,
            advertised_sessions: 74,
            called_when_advertised: 66,
            discovery_rate_pct: 89.2,
            description: 'Run a ClickHouse SQL query against events, persons, and warehouse tables.',
            n_clusters_served: 3,
            clusters: [
                {
                    cluster_id: 1,
                    calls: 1480,
                    capture_pct: 81.3,
                    rank: 1,
                    description_fit: 0.71,
                    top_competitor: { tool: 'read-data-schema', pct: 14.3 },
                },
                {
                    cluster_id: 3,
                    calls: 120,
                    capture_pct: 29.3,
                    rank: 2,
                    description_fit: 0.44,
                    top_competitor: { tool: 'read-data-schema', pct: 36.6 },
                },
            ],
        },
        {
            // Well described but rarely picked when advertised: the scatter's lower right.
            tool: 'read-data-schema',
            call_count: 540,
            error_count: 5,
            session_count: 58,
            contested_score: 0.66,
            advertised_sessions: 74,
            called_when_advertised: 18,
            discovery_rate_pct: 24.3,
            description: 'List the events, properties, and property values available in the project.',
            n_clusters_served: 3,
            clusters: [
                {
                    cluster_id: 3,
                    calls: 150,
                    capture_pct: 36.6,
                    rank: 1,
                    description_fit: 0.78,
                    top_competitor: { tool: 'execute-sql', pct: 29.3 },
                },
            ],
        },
        {
            // No description and too few advertised sessions, so fit and discovery are unmeasurable.
            tool: 'insight-create',
            call_count: 370,
            error_count: 8,
            session_count: 30,
            contested_score: 0.52,
            advertised_sessions: 3,
            called_when_advertised: 2,
            discovery_rate_pct: null,
            description: null,
            n_clusters_served: 2,
            clusters: [
                {
                    cluster_id: 2,
                    calls: 320,
                    capture_pct: 46.4,
                    rank: 1,
                    description_fit: null,
                    top_competitor: { tool: 'query-trends', pct: 34.8 },
                },
            ],
        },
    ],
    tool_overlaps: [
        {
            tool_a: 'execute-sql',
            tool_b: 'read-data-schema',
            contested_calls: 270,
            sessions_with_both: 41,
            sessions_with_either: 78,
        },
        {
            tool_a: 'insight-create',
            tool_b: 'query-trends',
            contested_calls: 140,
            sessions_with_both: 9,
            sessions_with_either: 44,
        },
    ],
}

// [tool, intent, durationMs, client, errorMessage]
const ACTIVITY_CALLS: [string, string | null, number | null, string, string | null][] = [
    [
        'feature-flag-get-all',
        'Searching PROD feature flags for scope-related keys as a broader sanity check.',
        174,
        '',
        null,
    ],
    [
        'switch-project',
        'Switching to the PROD project to cross-check the participant scope config flag.',
        154,
        '',
        null,
    ],
    ['execute-sql', 'Corroborate homepage INP p75 with its actual seven-day sample count.', 772, '', null],
    [
        'session-recording-summarize',
        "Verify whether the candidate's staff-route activity exposed protected content.",
        88000,
        '',
        null,
    ],
    [
        'read-data-schema',
        'Locate existing background prefetch events for the post-deployment smoke check.',
        601,
        '',
        null,
    ],
    ['exec', 'Signals scout run: discover durable-memory write tool.', null, '', null],
    ['logs-services-create', 'Checking whether backend log services could corroborate a failed signup.', 274, '', null],
    [
        'exec',
        'Learning read-data-schema tool schema to discover available events and properties.',
        2,
        'claude-code',
        null,
    ],
    ['exec', 'Learning execute-sql tool schema to run custom queries for adoption metrics.', 1, 'claude-code', null],
    [
        'scout-scratchpad-search',
        'Retrieve the full coverage map before refreshing the player-refresh watchpoint.',
        47,
        '',
        null,
    ],
    [
        'read-data-schema',
        'Verify the captured Web Vitals property for homepage INP sample counting.',
        517,
        'claude-code',
        null,
    ],
    ['query-trends', 'Chart weekly active agents to see whether adoption is still climbing.', 1320, 'cursor', null],
    [
        'insight-create',
        'Save the retention breakdown so the team can track it without re-querying.',
        940,
        'cursor',
        null,
    ],
    [
        'cohort-create',
        'Build a cohort of agents that hit an error in their first session.',
        1620,
        'claude-ai',
        'Cohort name already exists in this project',
    ],
    ['dashboard-create', 'Assemble the adoption dashboard from the insights created earlier.', 1180, 'claude-ai', null],
    ['execute-sql', 'Break down tool errors by client to find which harness fails most.', 3525, 'posthog-cli', null],
    [
        'feature-flag-list',
        'Audit which flags are still referenced before proposing cleanups.',
        510,
        'posthog-cli',
        null,
    ],
    ['query-trends', 'Compare this week against last to confirm the drop is not seasonal.', 2122, '', null],
    [
        'exec',
        'Retry the durable-memory write now that the schema is known.',
        30000,
        'windsurf',
        'Tool timed out after 30s',
    ],
    ['read-data-schema', 'Final schema sweep to confirm no event was missed in the audit.', 380, '', null],
]

const ACTIVITY_OVERVIEW = {
    // A project still under the ~300-call metrics gate, which is who lands on this tab.
    stats: {
        total_calls: 284,
        distinct_tools: 9,
        distinct_sessions: 23,
        distinct_clients: 6,
        calls_with_intent: 236,
        error_calls: 12,
        missing_capability_reports: 7,
    },
    // Top 5 of 9 tools, so these sum under total_calls; their errors sum to error_calls.
    top_tools: [
        { tool: 'exec', calls: 96, errors: 5 },
        { tool: 'execute-sql', calls: 64, errors: 4 },
        { tool: 'read-data-schema', calls: 43, errors: 1 },
        { tool: 'query-trends', calls: 31, errors: 1 },
        { tool: 'insight-create', calls: 22, errors: 1 },
    ],
    // Sums to stats.total_calls, so the card agrees with the summary line above it.
    clients: [
        { client: '', calls: 148 },
        { client: 'claude-code', calls: 71 },
        { client: 'cursor', calls: 33 },
        { client: 'claude-ai', calls: 18 },
        { client: 'posthog-cli', calls: 9 },
        { client: 'windsurf', calls: 5 },
    ],
    recent_calls: ACTIVITY_CALLS.map(([tool, intent, duration_ms, client_name, error_message], index) => ({
        // Spaced off the story's mockDate so the relative "when" column stays deterministic.
        timestamp: dayjs('2026-06-07T12:00:00Z')
            .subtract(index * 37, 'second')
            .toISOString(),
        tool,
        intent,
        is_error: error_message !== null,
        error_message,
        duration_ms,
        client_name,
    })),
}

const INTENT_DIGEST = {
    digest: 'Agents are extensively analyzing and validating feature flags, especially participant and scope-related flags, across multiple projects to ensure correct configuration and deployment. They are investigating user behavior, event schemas, and telemetry to support product analytics, adoption, and revenue reporting, and to diagnose issues such as interface unresponsiveness, conversion tracking failures, and LLM-related errors. Additionally, they are auditing dashboards, saved insights, and survey data to verify data freshness and rebuild product usage metrics.',
    intent_count: 100,
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/MCP Analytics',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/mcp_analytics/intent_clusters/': CLUSTER_SNAPSHOT,
                '/api/projects/:team_id/mcp_analytics/sessions/activity_overview/': ACTIVITY_OVERVIEW,
                '/api/environments/:team_id/mcp_analytics/sessions/': SESSION_LIST,
                '/api/environments/:team_id/mcp_analytics/sessions/:session_id/tool_calls/': TOOL_CALL_LIST,
                '/api/projects/:team_id/property_definitions': ({ request }) => {
                    const isFeatureFlag = new URL(request.url).searchParams.get('is_feature_flag') === 'true'
                    return [200, isFeatureFlag ? MCP_FEATURE_FLAG_DEFINITIONS : MCP_PROPERTY_DEFINITIONS]
                },
                '/api/environments/:team_id/events/values/': [
                    { name: 'execute-sql' },
                    { name: 'read-data-schema' },
                    { name: 'query-trends' },
                ],
            },
            post: {
                // POST, not GET — the endpoint generates the digest (and caches it) on call.
                '/api/projects/:team_id/mcp_analytics/sessions/intent_digest/': INTENT_DIGEST,
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    const query: string = body?.query?.query ?? ''
                    // The harness tile sends a typed MCPHarnessBreakdownQuery node (the runner
                    // resolves the harness server-side) — match on its kind, not a SQL string.
                    if (body?.query?.kind === 'MCPHarnessBreakdownQuery') {
                        return [200, { results: HARNESS_RESULTS }]
                    }
                    // Tool quality tab runners return typed item rows — match on kind, not a SQL string.
                    if (body?.query?.kind === 'MCPToolQualityRowsQuery') {
                        const rows = TOOL_QUALITY_ROWS.map((r) => ({
                            tool: r[0],
                            total_calls: r[1],
                            errors: r[2],
                            error_rate_pct: r[3],
                            p50_duration_ms: r[4],
                            p95_duration_ms: r[5],
                            p99_duration_ms: r[6],
                            users: r[7],
                            sessions: r[8],
                            first_seen: r[9],
                            last_seen: r[10],
                        }))
                        const search = String(body.query.search ?? '')
                            .trim()
                            .toLowerCase()
                        const filteredRows = search
                            ? rows.filter((row) => row.tool.toLowerCase().includes(search))
                            : rows
                        const sortColumn = String(body.query.sortColumn ?? 'total_calls')
                        const sortDirection = body.query.sortDirection === 'ASC' ? 1 : -1
                        filteredRows.sort((left, right) => {
                            const leftValue = left[sortColumn as keyof typeof left]
                            const rightValue = right[sortColumn as keyof typeof right]
                            const comparison =
                                typeof leftValue === 'number' && typeof rightValue === 'number'
                                    ? leftValue - rightValue
                                    : String(leftValue).localeCompare(String(rightValue))
                            return comparison === 0 ? left.tool.localeCompare(right.tool) : comparison * sortDirection
                        })
                        const limit = Number(body.query.limit ?? 50)
                        const offset = Number(body.query.offset ?? 0)
                        const page = filteredRows.slice(offset, offset + limit)
                        return [
                            200,
                            {
                                results: page,
                                totalCount: filteredRows.length,
                            },
                        ]
                    }
                    if (body?.query?.kind === 'MCPToolQualityDailyStatsQuery') {
                        return [
                            200,
                            {
                                results: DAILY_STATS.map((r) => ({
                                    day: r[0],
                                    calls: r[1],
                                    errors: r[2],
                                    p50: r[3],
                                    p95: r[4],
                                    p99: r[5],
                                })),
                            },
                        ]
                    }
                    if (body?.query?.kind === 'MCPToolCallBreakdownQuery') {
                        return [
                            200,
                            {
                                results: TOOL_DAILY_RESULTS.map(([bucket, tool, calls]) => ({
                                    bucket,
                                    tool,
                                    calls,
                                })),
                            },
                        ]
                    }
                    if (body?.query?.kind === 'MCPToolCallsAndErrorsQuery') {
                        return [
                            200,
                            {
                                results: ACTIVITY_RESULTS.map(([bucket, successes, errors]) => ({
                                    bucket,
                                    successes,
                                    errors,
                                })),
                            },
                        ]
                    }
                    if (body?.query?.kind === 'MCPToolCategoriesQuery') {
                        return [200, { results: CATEGORY_LIST.map((r) => ({ category: r[0] })) }]
                    }
                    if (body?.query?.kind === 'MCPToolCategoryMapQuery') {
                        return [200, { results: TOOL_CATEGORY_MAP.map((r) => ({ tool: r[0], category: r[1] })) }]
                    }
                    if (body?.query?.kind === 'MCPToolCategoryCountsQuery') {
                        return [200, { results: CATEGORY_COUNTS.map((r) => ({ category: r[0], calls: r[1] })) }]
                    }
                    // Onboarding gate: report the project as instrumented so the scene
                    // renders the dashboard/tabs instead of the empty state.
                    if (query.includes('has_initialize')) {
                        return [200, { results: [[true, true]] }]
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
        mockDate: '2026-06-07T12:00:00Z',
        pageUrl: urls.mcpAnalyticsDashboard(),
        featureFlags: [FEATURE_FLAGS.MCP_ANALYTICS],
    },
}
export default meta

type Story = StoryObj<{}>

export const Dashboard: Story = {}

// Re-list MCP_ANALYTICS — per-story featureFlags replace meta's, not merge with it.
export const DashboardWithMenuBar: Story = {
    parameters: {
        featureFlags: [FEATURE_FLAGS.MCP_ANALYTICS, FEATURE_FLAGS.SCENE_MENU_BAR],
    },
}

// The default landing tab for low-volume projects. The feed mock carries the endpoint's full
// 20-row cap so the feed overflows its viewport — the case where it has to scroll rather than
// stretch the grid past the sidebar.
export const Activity: Story = {
    parameters: {
        pageUrl: urls.mcpAnalyticsActivity(),
    },
}

export const Sessions: Story = {
    parameters: {
        pageUrl: urls.mcpAnalyticsSessions(),
    },
}

export const ToolQuality: Story = {
    parameters: {
        pageUrl: urls.mcpAnalyticsToolQuality(),
        // Quill charts paint to canvas asynchronously; skip the draw so the
        // snapshot stays deterministic. The surrounding layout/text — what
        // catches theme regressions — is still captured.
        testOptions: { skipCanvasDraw: true },
    },
}

export const IntentClustering: Story = {
    parameters: {
        pageUrl: urls.mcpAnalyticsIntentClustering(),
        featureFlags: [FEATURE_FLAGS.MCP_ANALYTICS, FEATURE_FLAGS.MCP_ANALYTICS_INTENT_ROUTING],
    },
}
