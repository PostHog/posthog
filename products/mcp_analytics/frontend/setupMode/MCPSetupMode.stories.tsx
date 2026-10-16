import { Meta, StoryObj } from '@storybook/react'

import { ProductEmptyState } from 'lib/components/ProductEmptyState/ProductEmptyState'
import { productEmptyStateStory } from 'lib/components/ProductEmptyState/storybookHelpers'
import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'

import { mcpAnalyticsEmptyState } from '../emptyState/mcpAnalyticsEmptyState'
import type { MCPActivityOverviewApi, MCPActivityRecentCallApi } from '../generated/api.schemas'
import { MCPSetupModeView, type MCPSetupModeViewProps } from './MCPSetupModeView'

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

const BASE: MCPSetupModeViewProps = {
    step: 'connect',
    connectState: { kind: 'waiting' },
    setupPath: 'agent',
    wizardCommand: 'npx -y @posthog/wizard@latest mcp-analytics --region us --project-id 997',
    recentCalls: null,
    recentCallsFailed: false,
    agentPrompt:
        'Install PostHog MCP analytics in the MCP server in this repository. Target PostHog project 997 at https://us.posthog.com.',
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

export const ConnectFromWizard: Story = {
    args: { setupPath: 'wizard' },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}

export const Connected: Story = {
    args: { connectState: { kind: 'connected' } },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}

export const FirstCallSuccess: Story = {
    args: { step: 'first-call', recentCalls: [SUCCESS_CALL] },
}

export const FirstCallWithFailure: Story = {
    args: { step: 'first-call', recentCalls: [FAILED_CALL, SUCCESS_CALL] },
    parameters: { testOptions: { viewportWidths: ['narrow', 'medium'] } },
}

export const FirstCallWithoutIntent: Story = {
    args: { step: 'first-call', recentCalls: [{ ...SUCCESS_CALL, intent: null, client_name: null }] },
}

export const MakeItUseful: Story = {
    args: { step: 'useful' },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud' },
                '/api/projects/:team_id/mcp_analytics/sessions/activity_overview/': OVERVIEW,
                '/api/projects/:team_id/hog_functions': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/subscriptions': EMPTY_PAGINATED_RESPONSE,
            },
        }),
    ],
    parameters: {
        featureFlags: [FEATURE_FLAGS.SUBSCRIPTION_AI_PROMPT],
        testOptions: { waitForSelector: '[data-attr=mcp-analytics-activity-next-step-weekly-report]' },
    },
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

// The setup screen with setup mode on: the wizard command and the agent prompt as two routes, and the demo card.
export const SetupScreen: StoryObj<typeof ProductEmptyState> = {
    ...SETUP_SCREEN,
    parameters: { ...SETUP_SCREEN.parameters, featureFlags: [FEATURE_FLAGS.MCP_ANALYTICS_SETUP_MODE] },
}
