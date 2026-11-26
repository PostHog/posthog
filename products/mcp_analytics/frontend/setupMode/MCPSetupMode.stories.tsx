import { MOCK_DEFAULT_ORGANIZATION } from '~/lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'

import { ProductEmptyState } from 'lib/components/ProductEmptyState/ProductEmptyState'
import { productEmptyStateStory } from 'lib/components/ProductEmptyState/storybookHelpers'
import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'

import { userEvent } from 'storybook/test'

import { mcpAnalyticsEmptyState } from '../emptyState/mcpAnalyticsEmptyState'
import type { MCPActivityOverviewApi, MCPActivityRecentCallApi } from '../generated/api.schemas'
import { MCPSetupModeView, type MCPSetupModeViewProps } from './MCPSetupModeView'
import type { MCPServerTools } from './setupMode'

// Invented fixtures: an example docs server called from two clients.
const SUCCESS_CALL: MCPActivityRecentCallApi = {
    timestamp: '2026-06-07T11:59:40Z',
    tool: 'search_docs',
    intent: 'Find the rate limit for the billing API so I can add retries',
    is_error: false,
    error_message: null,
    duration_ms: 142,
    client_name: 'Claude Code',
}

const FAILED_CALL: MCPActivityRecentCallApi = {
    timestamp: '2026-06-07T11:59:55Z',
    tool: 'create_issue',
    intent: 'Open a ticket for the 429 errors the user reported',
    is_error: true,
    error_message: 'ValidationError: missing required field "team_id"',
    duration_ms: 88,
    client_name: 'Cursor',
}

// Invented: the tools an example docs server lists, before and after its first two calls.
const LISTED_TOOLS = ['search_docs', 'create_issue', 'run_query', 'list_feature_flags', 'get_schema']
const TOOLS_BEFORE_CALLS: MCPServerTools = { listed: LISTED_TOOLS, called: [] }
const TOOLS_AFTER_CALLS: MCPServerTools = { listed: LISTED_TOOLS, called: ['search_docs', 'create_issue'] }

const BASE: MCPSetupModeViewProps = {
    step: 'connect',
    connectState: { kind: 'waiting' },
    recentCalls: null,
    recentCallsFailed: false,
    toolCallsTotal: 2,
    serverTools: null,
    serverToolsFailed: false,
    onExit: () => {},
    onAskPostHogAI: () => {},
    onGoToUseful: () => {},
}

const OVERVIEW: MCPActivityOverviewApi = {
    stats: {
        total_calls: 2,
        distinct_tools: 2,
        distinct_sessions: 1,
        distinct_clients: 2,
        calls_with_intent: 2,
        error_calls: 1,
        missing_capability_reports: 0,
    },
    top_tools: [],
    clients: [],
    recent_calls: [FAILED_CALL, SUCCESS_CALL],
}

const meta: Meta<typeof MCPSetupModeView> = {
    title: 'Scenes-App/MCP Analytics/Setup mode',
    component: MCPSetupModeView,
    decorators: [
        (Story) => (
            <div className="flex h-screen">
                <Story />
            </div>
        ),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-07T12:00:00Z',
    },
    args: BASE,
}
export default meta

type Story = StoryObj<typeof MCPSetupModeView>

export const Connect: Story = {
    parameters: { testOptions: { viewportWidths: ['narrow', 'medium'], waitForLoadersToDisappear: false } },
}

export const Connected: Story = {
    args: { connectState: { kind: 'connected' }, serverTools: TOOLS_BEFORE_CALLS },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}

export const ConnectedBeforeToolsList: Story = {
    args: { connectState: { kind: 'connected' }, serverTools: { listed: null, called: [] } },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}

export const FirstCallSuccess: Story = {
    args: {
        step: 'first-call',
        recentCalls: [SUCCESS_CALL],
        serverTools: { listed: LISTED_TOOLS, called: ['search_docs'] },
    },
}

export const FirstCallWithFailure: Story = {
    args: { step: 'first-call', recentCalls: [FAILED_CALL, SUCCESS_CALL], serverTools: TOOLS_AFTER_CALLS },
    parameters: { testOptions: { viewportWidths: ['narrow', 'medium'] } },
}

export const FirstCallWithoutIntent: Story = {
    args: {
        step: 'first-call',
        recentCalls: [{ ...SUCCESS_CALL, intent: null, client_name: null }],
        serverTools: { listed: LISTED_TOOLS, called: ['search_docs'] },
    },
}

const WEEKLY_REPORT_BUTTON = '[data-attr=mcp-analytics-activity-next-step-weekly-report]'

const USEFUL_GET_MOCKS = {
    '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud' },
    '/api/projects/:team_id/mcp_analytics/sessions/activity_overview/': OVERVIEW,
    '/api/projects/:team_id/hog_functions': EMPTY_PAGINATED_RESPONSE,
    '/api/projects/:team_id/subscriptions': EMPTY_PAGINATED_RESPONSE,
}

export const MakeItUseful: Story = {
    args: { step: 'useful', recentCalls: [FAILED_CALL, SUCCESS_CALL] },
    decorators: [mswDecorator({ get: USEFUL_GET_MOCKS })],
    parameters: {
        featureFlags: [FEATURE_FLAGS.SUBSCRIPTION_AI_PROMPT],
        testOptions: { waitForSelector: WEEKLY_REPORT_BUTTON },
    },
}

// A bare querySelector misses while the card is still loading, and the click would silently do nothing.
async function clickWeeklyReportButton(): Promise<void> {
    const button = await waitFor(
        () => {
            const element = document.querySelector<HTMLElement>(WEEKLY_REPORT_BUTTON)
            if (!element) {
                throw new Error('The weekly report button is not rendered')
            }
            return element
        },
        { timeout: 15000 }
    )
    await userEvent.click(button)
}

export const MakeItUsefulReportFailed: Story = {
    args: MakeItUseful.args,
    decorators: [
        mswDecorator({
            get: USEFUL_GET_MOCKS,
            post: {
                '/api/projects/:team_id/subscriptions': (): [number, { detail: string }] => [
                    400,
                    { detail: 'Your plan is limited to 5 subscriptions.' },
                ],
            },
        }),
    ],
    parameters: {
        featureFlags: [FEATURE_FLAGS.SUBSCRIPTION_AI_PROMPT],
        testOptions: { waitForSelector: '[role=alert]' },
    },
    play: clickWeeklyReportButton,
}

export const MakeItUsefulReportNeedsConsent: Story = {
    args: MakeItUseful.args,
    decorators: [
        mswDecorator({
            get: {
                ...USEFUL_GET_MOCKS,
                '/api/organizations/@current/': { ...MOCK_DEFAULT_ORGANIZATION, is_ai_data_processing_approved: false },
            },
        }),
    ],
    parameters: {
        featureFlags: [FEATURE_FLAGS.SUBSCRIPTION_AI_PROMPT],
        testOptions: { waitForSelector: '[data-attr=ai-consent-approve]' },
    },
    play: clickWeeklyReportButton,
}

const SETUP_SCREEN = productEmptyStateStory(mcpAnalyticsEmptyState, 'needs-setup', {
    mocks: {
        get: { '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud' } },
        post: {
            // Onboarding signals: [has_initialize, tool_calls_total, tool_calls_7d, first_call_at]
            '/api/environments/:team_id/query/:kind': [200, { results: [[0, 0, 0, '1970-01-01T00:00:00Z']] }],
        },
    },
})

// The setup screen with setup mode on: the Start setup card, and the how-it-works sidebar above the
// demo card. At medium width the stacked sidebar is wide enough for its three-column layout.
export const SetupScreen: StoryObj<typeof ProductEmptyState> = {
    ...SETUP_SCREEN,
    parameters: {
        ...SETUP_SCREEN.parameters,
        featureFlags: [FEATURE_FLAGS.MCP_ANALYTICS_SETUP_MODE],
        testOptions: { ...SETUP_SCREEN.parameters?.testOptions, viewportWidths: ['narrow', 'medium', 'wide'] },
    },
}
