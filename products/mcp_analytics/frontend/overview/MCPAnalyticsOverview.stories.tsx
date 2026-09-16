import { MOCK_DEFAULT_USER } from '~/lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { MCPAnalyticsOverview } from './MCPAnalyticsOverview'

interface OverviewDataset {
    summary: Record<string, unknown>
    harnessRows: Record<string, unknown>[]
    modelRows: Record<string, unknown>[]
    failureGroups: Record<string, unknown>[]
    intentDigest: Record<string, unknown>
    missingReports: Record<string, unknown>[]
}

// Invented figures at a busy server's order of magnitude. They are not any real server's numbers.
const BUSY: OverviewDataset = {
    summary: {
        people: 40000,
        new_people: 12000,
        returning_people: 28000,
        new_people_first_call_failed_pct: 10.3,
        calls: 3200000,
        sessions: 250000,
        success_pct: 96,
        intent_pct: 88,
        clients: 28,
        automation_calls: 4000000,
        automation_sessions: 120000,
    },
    harnessRows: [
        { harness: 'Claude Code', total_calls: 1200000, errors: 68400, error_rate_pct: 5.7, sessions: 100000 },
        { harness: 'OpenAI Codex', total_calls: 800000, errors: 16000, error_rate_pct: 2, sessions: 70000 },
        { harness: 'Cursor', total_calls: 400000, errors: 14000, error_rate_pct: 3.5, sessions: 36000 },
        { harness: 'Claude Desktop', total_calls: 120000, errors: 6600, error_rate_pct: 5.5, sessions: 11000 },
        { harness: 'Other', total_calls: 480000, errors: 72000, error_rate_pct: 15, sessions: 40000 },
    ],
    modelRows: [
        { model: 'claude-opus-5', total_calls: 500000, errors: 20000, error_rate_pct: 4 },
        { model: 'claude-sonnet-5', total_calls: 300000, errors: 12000, error_rate_pct: 4 },
        { model: 'gpt-5.6-sol', total_calls: 200000, errors: 8000, error_rate_pct: 4 },
        { model: 'Unknown', total_calls: 1600000, errors: 0, error_rate_pct: 0 },
    ],
    failureGroups: [
        {
            tool: 'execute-sql',
            error_type: 'internal',
            message: 'Tool execute-sql returned an error',
            sessions: 18000,
            calls: 72000,
            people: 9000,
            next_retried_succeeded_pct: 46,
            next_retried_failed_pct: 4,
            next_switched_pct: 47,
            next_ended_pct: 3,
            sample_intent: 'Pinning down when a checkout error started, at five-minute resolution.',
        },
        {
            tool: 'exec',
            error_type: 'validation',
            message: 'exec rejected the call: unknown_tool',
            sessions: 22000,
            calls: 66000,
            people: 11000,
            next_retried_succeeded_pct: 6,
            next_retried_failed_pct: 14,
            next_switched_pct: 63,
            next_ended_pct: 17,
            sample_intent: 'Looking for a tool that exports a cohort to CSV.',
        },
        {
            tool: 'query-logs',
            error_type: 'validation',
            message: 'query-logs called without the query wrapper: fields were sent at the top level',
            sessions: 5400,
            calls: 5600,
            people: 3100,
            next_retried_succeeded_pct: 1,
            next_retried_failed_pct: 1,
            next_switched_pct: 98,
            next_ended_pct: 0,
            sample_intent: 'Reading backend logs around a failed deploy.',
        },
        {
            tool: 'insight-create',
            error_type: 'internal',
            message: 'insight-create returned an error with no detail',
            sessions: 700,
            calls: 3300,
            people: 500,
            next_retried_succeeded_pct: 9,
            next_retried_failed_pct: 21,
            next_switched_pct: 40,
            next_ended_pct: 30,
            sample_intent: 'Building a trend of failed sign-in attempts to hang an alert off.',
        },
    ],
    intentDigest: {
        digest: 'Agents mostly investigate metric drops, check the schema before querying, and build or update insights.',
        intent_count: 1000,
        themes: [
            {
                name: 'Investigate a drop or incident in a metric',
                description: 'Agents narrow down when a metric moved and what moved with it.',
                intent_count: 310,
                example_intent: 'Pinning down the start, peak and end of the checkout error spike.',
                tools: ['execute-sql', 'query-trends'],
                error_count: 9,
                success_pct: 97,
            },
            {
                name: 'Check the schema before querying',
                description: 'Agents confirm property names before writing a query.',
                intent_count: 240,
                example_intent: 'Confirming the property names on the tool-call event before counting by integration.',
                tools: ['read-data-schema'],
                error_count: 2,
                success_pct: 99,
            },
            {
                name: 'Build or update insights and dashboards',
                description: 'Agents create insights and hang them on a dashboard.',
                intent_count: 140,
                example_intent: 'Creating a trend that counts authentication refresh failures.',
                tools: ['insight-create', 'dashboard-get'],
                error_count: 10,
                success_pct: 93,
            },
            {
                name: 'Look up feature flags and experiments',
                description: 'Agents check whether a flag or experiment already exists.',
                intent_count: 120,
                example_intent: 'Checking whether the flag referenced by a merged change already exists.',
                tools: ['feature-flag-get-all'],
                error_count: 11,
                success_pct: 91,
            },
            {
                name: "Trace one person's timeline",
                description: 'Agents reconstruct what one person did around a failure.',
                intent_count: 100,
                example_intent: 'Reconstructing a timeline to diagnose an error during a subscription attempt.',
                tools: ['execute-sql', 'query-session-recordings-list'],
                error_count: 5,
                success_pct: 95,
            },
        ],
    },
    missingReports: [],
}

const SMALL: OverviewDataset = {
    summary: {
        people: 31,
        new_people: 12,
        returning_people: 19,
        new_people_first_call_failed_pct: 25,
        calls: 480,
        sessions: 212,
        success_pct: 91,
        intent_pct: 46,
        clients: 3,
        automation_calls: 0,
        automation_sessions: 0,
    },
    harnessRows: [
        { harness: 'Claude Code', total_calls: 290, errors: 20, error_rate_pct: 7, sessions: 120 },
        { harness: 'Cursor', total_calls: 120, errors: 14, error_rate_pct: 12, sessions: 60 },
        { harness: 'ChatGPT', total_calls: 70, errors: 6, error_rate_pct: 9, sessions: 32 },
    ],
    modelRows: [
        { model: 'claude-sonnet-5', total_calls: 210, errors: 8, error_rate_pct: 4 },
        { model: 'gpt-5.6-sol', total_calls: 80, errors: 3, error_rate_pct: 4 },
        { model: 'Unknown', total_calls: 190, errors: 0, error_rate_pct: 0 },
    ],
    failureGroups: [
        {
            tool: 'create_refund',
            error_type: 'validation',
            message: 'Error: amount exceeds refundable balance',
            sessions: 9,
            calls: 26,
            people: 7,
            next_retried_succeeded_pct: 61,
            next_retried_failed_pct: 8,
            next_switched_pct: 0,
            next_ended_pct: 31,
            sample_intent: 'Refunding a duplicate charge after confirming both invoices are on one subscription.',
        },
        {
            tool: 'get_order',
            error_type: 'validation',
            message: 'get_order called with orderId instead of order_id',
            sessions: 6,
            calls: 11,
            people: 5,
            next_retried_succeeded_pct: 100,
            next_retried_failed_pct: 0,
            next_switched_pct: 0,
            next_ended_pct: 0,
            sample_intent: 'Looking up the shipment status for an order so support can reply.',
        },
    ],
    intentDigest: {
        digest: 'Support agents look up orders, issue refunds, and update customer contact details.',
        intent_count: 221,
        themes: [
            {
                name: 'Find the status of an order',
                description: 'Agents look up where an order is for a waiting customer.',
                intent_count: 115,
                example_intent: 'Looking up the latest shipment status so support can reply to the customer.',
                tools: ['get_order', 'list_shipments'],
                error_count: 5,
                success_pct: 96,
            },
            {
                name: 'Issue or check a refund',
                description: 'Agents refund a charge or confirm one already went out.',
                intent_count: 64,
                example_intent: 'Refunding a duplicate charge after confirming both invoices are on one subscription.',
                tools: ['create_refund', 'get_invoice'],
                error_count: 18,
                success_pct: 71,
            },
            {
                name: "Update a customer's contact details",
                description: 'Agents change the address or email on an account.',
                intent_count: 42,
                example_intent: 'Changing the billing email after the customer asked in chat.',
                tools: ['update_customer'],
                error_count: 0,
                success_pct: 100,
            },
        ],
    },
    missingReports: [
        {
            timestamp: '2026-06-06T10:12:00Z',
            intent: "Need a way to export the customer's invoices as CSV.",
            harness: 'Claude Code',
            session_id: 'sess-1',
            distinct_id: 'user-1',
            person_properties: '{}',
        },
    ],
}

function datasetDecorator(dataset: OverviewDataset): ReturnType<typeof mswDecorator> {
    const resultsByKind: Record<string, unknown[]> = {
        MCPOverviewSummaryQuery: [dataset.summary],
        MCPHarnessBreakdownQuery: dataset.harnessRows,
        MCPModelBreakdownQuery: dataset.modelRows,
        MCPFailureGroupsQuery: dataset.failureGroups,
        MCPMissingCapabilitiesQuery: dataset.missingReports,
    }
    return mswDecorator({
        get: {
            '/api/projects/:team_id/property_definitions': [],
            '/api/environments/:team_id/events/values/': [],
        },
        post: {
            // POST, not GET — the endpoint generates the digest (and caches it) on call.
            '/api/projects/:team_id/mcp_analytics/sessions/intent_digest/': dataset.intentDigest,
            '/api/environments/:team_id/query/:kind': async ({ request }) => {
                const body = (await request.json()) as Record<string, any>
                const kind: string = body?.query?.kind ?? ''
                if (kind in resultsByKind) {
                    return [200, { results: resultsByKind[kind], has_next: false }]
                }
                // Onboarding gate: report the project as instrumented so the scene renders
                // the tabs instead of the setup empty state.
                if (String(body?.query?.query ?? '').includes('has_initialize')) {
                    return [200, { results: [[true, dataset.summary.calls, 72, '2026-05-15T09:00:00Z']] }]
                }
                return [200, { results: [] }]
            },
        },
    })
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/MCP Analytics Overview',
    decorators: [
        (Story, context) =>
            mswDecorator({
                get: { '/api/users/@me/': { ...MOCK_DEFAULT_USER, theme_mode: context.globals.theme ?? 'light' } },
            })(Story, context),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-07T12:00:00Z',
        pageUrl: urls.mcpAnalyticsOverview(),
        featureFlags: [FEATURE_FLAGS.MCP_ANALYTICS],
        testOptions: { viewportWidths: ['medium', 'wide'] },
    },
}
export default meta

type Story = StoryObj<{}>

export const Overview: Story = {
    decorators: [datasetDecorator(BUSY)],
}

export const OverviewSmallServer: Story = {
    decorators: [datasetDecorator(SMALL)],
}

// The scene a nav sidebar plus an open side panel leaves behind.
export const OverviewNarrow: Story = {
    decorators: [datasetDecorator(SMALL)],
    parameters: { layout: 'padded' },
    render: () => (
        <div className="w-[520px]">
            <MCPAnalyticsOverview />
        </div>
    ),
}
