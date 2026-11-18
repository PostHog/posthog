import type { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { MCPGatewayServerApi, TeamMCPGatewayConfigApi } from '../generated/api.schemas'
import { GatewayConnectionModal } from './GatewayConnectionModal'
import { mcpGatewayLogic } from './mcpGatewayLogic'

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

function gatewayServer(overrides: Partial<MCPGatewayServerApi>): MCPGatewayServerApi {
    return {
        id: 'server-id',
        name: 'Internal wiki',
        url: 'https://mcp.wiki.example.com/mcp',
        description: '',
        category: 'productivity',
        template_auth_type: null,
        auth_type: null,
        is_team_enabled: true,
        icon_key: '',
        icon_domain: '',
        docs_url: '',
        template_id: null,
        tool_count: 4,
        connections: [],
        your_connection: null,
        agents: [],
        revoked_user_ids: [],
        is_revoked_for_you: false,
        created_by: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        ...overrides,
    }
}

function ConnectOnLoad({ serverId }: { serverId: string }): JSX.Element {
    const { servers } = useValues(mcpGatewayLogic)
    const { connectServer } = useActions(mcpGatewayLogic)
    useEffect(() => {
        if (servers.some((server) => server.id === serverId)) {
            connectServer(serverId)
        }
    }, [servers, serverId, connectServer])
    return <GatewayConnectionModal />
}

function storyFor(server: MCPGatewayServerApi): Story {
    return {
        decorators: [
            mswDecorator({
                get: {
                    '/api/projects/:project_id/mcp_gateway/servers/': () => [
                        200,
                        { ...EMPTY_PAGE, count: 1, results: [server] },
                    ],
                    '/api/projects/:project_id/mcp_gateway/config/': () => [200, GATEWAY_CONFIG],
                    '/api/projects/:project_id/mcp_gateway/service_accounts/': () => [200, EMPTY_PAGE],
                    '/api/projects/:project_id/mcp_gateway/rules/': () => [200, EMPTY_PAGE],
                    '/api/projects/:project_id/mcp_servers/': () => [200, EMPTY_PAGE],
                },
            }),
        ],
        render: () => <ConnectOnLoad serverId={server.id} />,
    }
}

type Story = StoryObj<typeof GatewayConnectionModal>
const meta: Meta<typeof GatewayConnectionModal> = {
    title: 'Scenes-App/MCP servers/Connect server modal',
    component: GatewayConnectionModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-01-15',
    },
}

export default meta

/** A teammate added this custom server with an API key: each member enters their own key. */
export const CustomServerAddedWithApiKey: Story = storyFor(gatewayServer({ auth_type: 'api_key' }))

/** A custom OAuth server keeps the optional client id and secret. */
export const CustomServerAddedWithOAuth: Story = storyFor(gatewayServer({ auth_type: 'oauth' }))

/** Custom servers registered before their auth type was recorded still let the member choose. */
export const CustomServerWithoutRecordedAuthType: Story = storyFor(gatewayServer({ auth_type: null }))

export const CatalogApiKeyTemplate: Story = storyFor(
    gatewayServer({
        id: 'template-server',
        name: 'Linear',
        template_id: 'template-id',
        template_auth_type: 'api_key',
        auth_type: 'api_key',
    })
)
