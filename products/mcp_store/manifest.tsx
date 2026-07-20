import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'MCP servers',
    scenes: {
        McpGateway: {
            import: () => import('./frontend/gateway/McpGatewayScene'),
            projectBased: true,
            name: 'MCP servers',
            description:
                'Route every MCP server your team uses through one gateway: shared credentials, per-tool policies, agent identities, and an audit log.',
            layout: 'app-container',
            iconType: 'tools',
        },
        McpGatewayServer: {
            import: () => import('./frontend/gateway/GatewayServerScene'),
            projectBased: true,
            name: 'MCP server',
        },
        McpGatewayAgent: {
            import: () => import('./frontend/gateway/GatewayAgentScene'),
            projectBased: true,
            name: 'MCP agent',
        },
        McpGatewayMember: {
            import: () => import('./frontend/gateway/GatewayMemberScene'),
            projectBased: true,
            name: 'MCP member access',
        },
    },
    routes: {
        // Specific routes must precede '/mcp-servers/:tab' so 'server' etc. don't match as tabs.
        '/mcp-servers/server/:id': ['McpGatewayServer', 'mcpGatewayServer'],
        '/mcp-servers/agent/:id': ['McpGatewayAgent', 'mcpGatewayAgent'],
        '/mcp-servers/member/:id': ['McpGatewayMember', 'mcpGatewayMember'],
        '/mcp-servers': ['McpGateway', 'mcpGateway'],
        '/mcp-servers/:tab': ['McpGateway', 'mcpGatewayTab'],
    },
    redirects: {},
    urls: {
        mcpGateway: (): string => '/mcp-servers',
        mcpGatewayTab: (tab: string): string => `/mcp-servers/${tab}`,
        mcpGatewayServer: (id: string, scope?: string): string =>
            `/mcp-servers/server/${id}${scope ? `?scope=${encodeURIComponent(scope)}` : ''}`,
        mcpGatewayAgent: (id: string): string => `/mcp-servers/agent/${id}`,
        mcpGatewayMember: (id: string | number): string => `/mcp-servers/member/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'MCP servers',
            intents: [],
            category: ProductItemCategory.AI_ENGINEERING,
            href: urls.mcpGateway(),
            iconType: 'tools',
            flag: FEATURE_FLAGS.MCP_GATEWAY,
            tags: ['alpha'],
            sceneKey: 'McpGateway',
        },
    ],
}
