/**
 * Product manifest for mcp_analytics.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor } from '../../frontend/src/types'
import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'MCP analytics',
    scenes: {
        // Define scenes here
        MCPAnalytics: {
            import: () => import('./frontend/MCPAnalyticsScene'),
            projectBased: true,
            name: 'MCP analytics',
            layout: 'app-container',
            description: 'Capture user intent and behaviour patterns to understand what AI users need from your tools.',
            iconType: 'llm_analytics',
        },
    },
    routes: {
        // Define routes here
        '/mcp-analytics/dashboard': ['MCPAnalytics', 'mcpAnalyticsDashboard'],
    },
    redirects: {},
    urls: {
        // Define URL helpers here
        mcpAnalyticsDashboard: (): string => '/mcp-analytics/dashboard',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'MCP analytics',
            intents: [ProductKey.LLM_ANALYTICS],
            category: ProductItemCategory.AI_ENGINEERING,
            visualOrder: 2,
            type: 'mcp_analytics',
            iconType: 'llm_analytics' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-analytics-light)'] as FileSystemIconColor,
            href: urls.mcpAnalyticsDashboard(),
            flag: FEATURE_FLAGS.MCP_ANALYTICS,
            sceneKey: 'MCPAnalytics',
        },
    ],
}
