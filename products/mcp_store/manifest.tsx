import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
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
    treeItemsProducts: [
        {
            path: 'MCP servers',
            category: 'Tools',
            intents: [ProductKey.MCP_STORE],
            href: urls.mcpStore(),
            flag: FEATURE_FLAGS.MCP_SERVERS,
            sceneKey: 'McpStore',
            sceneKeys: ['McpStore'],
        },
    ],
}
