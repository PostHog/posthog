import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { GatewayAgentAccessApi, MCPGatewayServerApi, UserBasicApi } from '../generated/api.schemas'

const SERVER_ID = 'srv-linear'

const you: UserBasicApi = {
    id: MOCK_DEFAULT_BASIC_USER.id,
    uuid: MOCK_DEFAULT_BASIC_USER.uuid,
    distinct_id: MOCK_DEFAULT_BASIC_USER.uuid,
    first_name: MOCK_DEFAULT_BASIC_USER.first_name,
    last_name: '',
    email: MOCK_DEFAULT_BASIC_USER.email,
}

const teammate: UserBasicApi = {
    id: 9001,
    uuid: '0198a2c4-2b1e-7d00-9c2b-1a2b3c4d5e6f',
    distinct_id: '0198a2c4-2b1e-7d00-9c2b-1a2b3c4d5e6f',
    first_name: 'Grace',
    last_name: 'Hopper',
    email: 'grace@example.com',
}

const agentShare = (
    handle: string,
    name: string,
    overrides: Partial<GatewayAgentAccessApi> = {}
): GatewayAgentAccessApi => ({
    service_account_id: `sa-${handle}`,
    user: you,
    scope: 'team',
    name,
    handle,
    status: 'active',
    last_active_at: null,
    granted_by: null,
    ...overrides,
})

const server: MCPGatewayServerApi = {
    id: SERVER_ID,
    name: 'Linear',
    url: 'https://mcp.linear.app/mcp',
    description: 'Issues, projects, and cycles.',
    category: 'productivity',
    template_auth_type: 'oauth',
    is_team_enabled: true,
    icon_key: '',
    icon_domain: 'linear.app',
    docs_url: 'https://linear.app/docs',
    template_id: 'tpl-linear',
    tool_count: 12,
    connections: [
        {
            installation_id: 'inst-you',
            user: you,
            last_used_at: '2024-07-09T10:00:00Z',
            pending_oauth: false,
            needs_reauth: false,
        },
        {
            installation_id: 'inst-teammate',
            user: teammate,
            last_used_at: null,
            pending_oauth: false,
            needs_reauth: false,
        },
    ],
    your_connection: {
        installation_id: 'inst-you',
        is_enabled: true,
        pending_oauth: false,
        needs_reauth: false,
        last_used_at: '2024-07-09T10:00:00Z',
    },
    agents: [
        agentShare('posthog-support', 'Support agent', { scope: 'personal' }),
        agentShare('posthog-scout', 'Scout agent', { last_active_at: '2024-07-09T11:24:00Z' }),
        agentShare('posthog-workflow', 'Workflow agent'),
        agentShare('release-notes', 'Release notes agent', { user: teammate, status: 'paused' }),
    ],
    revoked_user_ids: [],
    is_revoked_for_you: false,
    created_by: you,
    created_at: '2024-06-01T00:00:00Z',
    updated_at: '2024-07-09T00:00:00Z',
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/MCP gateway/Server',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-07-09T12:00:00Z',
        pageUrl: urls.mcpGatewayServer(SERVER_ID),
        featureFlags: [FEATURE_FLAGS.MCP_GATEWAY],
    },
    decorators: [
        mswDecorator({
            get: {
                // The default mock user carries no id, and the agent rows compare ids to find your own shares.
                'api/users/@me/': {
                    ...MOCK_DEFAULT_USER,
                    id: MOCK_DEFAULT_BASIC_USER.id,
                    organization: MOCK_DEFAULT_ORGANIZATION,
                    pending_invites: [],
                },
                'api/projects/:team_id/mcp_gateway/config/': {
                    allow_custom_servers: false,
                    allow_member_agent_access: true,
                    default_servers_enabled: true,
                    registered_template_ids: ['tpl-linear'],
                    is_admin: true,
                },
                'api/projects/:team_id/mcp_gateway/servers/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [server],
                },
                'api/projects/:team_id/mcp_gateway/servers/:id/': server,
                'api/projects/:team_id/mcp_gateway/servers/:id/tools/': { results: [] },
                'api/projects/:team_id/mcp_gateway/service_accounts/': {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                },
                'api/projects/:team_id/mcp_gateway/rules/': { count: 0, next: null, previous: null, results: [] },
                'api/projects/:team_id/mcp_gateway/members/': { count: 0, next: null, previous: null, results: [] },
                'api/projects/:team_id/mcp_servers/': { count: 0, next: null, previous: null, results: [] },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

// An admin who connected the server and shared it with three agents, plus one teammate share.
export const Page: Story = {}
