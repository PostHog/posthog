import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'MCP store',
    scenes: {
        McpStore: {
            name: 'MCP store',
            import: () => import('./frontend/McpStoreScene'),
            projectBased: true,
            activityScope: 'McpStore',
            description: 'Manage MCP servers for your AI agents.',
        },
    },
    routes: {
        '/mcp-store': ['McpStore', 'mcpStore'],
    },
    urls: {
        mcpStore: (): string => '/mcp-store',
    },
    treeItemsNew: [],
    treeItemsProducts: [],
}
