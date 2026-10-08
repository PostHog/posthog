import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'MCP registry',
    scenes: {
        MCPRegistry: {
            name: 'MCP registry',
            import: () => import('./frontend/MCPRegistryScene'),
            projectBased: true,
            description: 'Find an MCP server for a task, ranked by whether it answers and how well it works.',
        },
    },
    routes: {
        '/mcp-registry': ['MCPRegistry', 'mcpRegistry'],
    },
    redirects: {},
    urls: {
        mcpRegistry: (): string => '/mcp-registry',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    // No product tree entry yet: the index is behind the mcp-registry flag while it fills up,
    // so it is reached by URL rather than advertised in the nav.
    treeItemsProducts: [],
}
