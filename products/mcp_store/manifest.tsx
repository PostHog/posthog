import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'MCP servers',
    scenes: {
        McpStore: {
            name: 'MCP servers',
            import: () => import('./frontend/McpStoreScene'),
            projectBased: true,
            activityScope: 'McpStore',
            description: 'Manage MCP servers for your AI agents.',
        },
    },
    routes: {
        '/mcp-servers': ['McpStore', 'mcpStore'],
    },
    urls: {
        mcpStore: (): string => '/mcp-servers',
    },
    treeItemsNew: [],
    treeItemsProducts: [],
}
