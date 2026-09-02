import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { mswDecorator } from '~/mocks/browser'

import { MCPGatewayServerApi, TeamMCPGatewayConfigApi } from '../generated/api.schemas'
import { gatewayServerLogic } from './gatewayServerLogic'
import { GatewayServerScene } from './GatewayServerScene'

const EMPTY_PAGE = { count: 0, next: null, previous: null, results: [] }

const GATEWAY_CONFIG: TeamMCPGatewayConfigApi = {
    allow_custom_servers: true,
    allow_member_agent_access: true,
    default_servers_enabled: true,
    member_default_preset: '',
    agent_default_preset: '',
    registered_template_ids: [],
    is_admin: false,
}

const SERVER: MCPGatewayServerApi = {
    id: 'server-id',
    name: 'Internal wiki',
    url: 'https://mcp.wiki.example.com/mcp',
    description: 'Search the team wiki.',
    category: 'productivity',
    template_auth_type: null,
    auth_type: 'api_key',
    is_team_enabled: true,
    icon_key: '',
    icon_domain: '',
    docs_url: '',
    template_id: null,
    tool_count: 0,
    connections: [],
    your_connection: null,
    agents: [],
    revoked_user_ids: [],
    is_revoked_for_you: false,
    created_by: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
}

type Story = StoryObj<typeof GatewayServerScene>
const meta: Meta<typeof GatewayServerScene> = {
    title: 'Scenes-App/MCP servers/Server detail',
    component: GatewayServerScene,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-01-15',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:project_id/mcp_gateway/servers/': () => [
                    200,
                    { ...EMPTY_PAGE, count: 1, results: [SERVER] },
                ],
                '/api/projects/:project_id/mcp_gateway/servers/:server_id/tools/': () => [200, { results: [] }],
                '/api/projects/:project_id/mcp_gateway/config/': () => [200, GATEWAY_CONFIG],
                '/api/projects/:project_id/mcp_gateway/service_accounts/': () => [200, EMPTY_PAGE],
                '/api/projects/:project_id/mcp_gateway/rules/': () => [200, EMPTY_PAGE],
                '/api/projects/:project_id/mcp_gateway/members/': () => [200, EMPTY_PAGE],
                '/api/projects/:project_id/mcp_servers/': () => [200, EMPTY_PAGE],
            },
        }),
    ],
}

export default meta

/** A member who has not connected yet. "Connect your account" opens the connection modal here. */
export const NotConnected: Story = {
    render: () => (
        <BindLogic logic={gatewayServerLogic} props={{ id: SERVER.id }}>
            <GatewayServerScene id={SERVER.id} />
        </BindLogic>
    ),
}
