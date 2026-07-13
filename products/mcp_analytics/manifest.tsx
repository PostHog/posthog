/**
 * Product manifest for mcp_analytics.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { combineUrl } from 'kea-router'

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
        MCPAnalyticsToolDetail: {
            import: () => import('./frontend/MCPAnalyticsToolDetail'),
            projectBased: true,
            name: 'MCP tool',
            layout: 'app-container',
            iconType: 'llm_analytics',
        },
    },
    routes: {
        // Define routes here
        '/mcp-analytics/activity': ['MCPAnalytics', 'mcpAnalyticsActivity'],
        '/mcp-analytics/dashboard': ['MCPAnalytics', 'mcpAnalyticsDashboard'],
        '/mcp-analytics/sessions': ['MCPAnalytics', 'mcpAnalyticsSessions'],
        '/mcp-analytics/tool-quality': ['MCPAnalytics', 'mcpAnalyticsToolQuality'],
        '/mcp-analytics/tool-quality/:toolName': ['MCPAnalyticsToolDetail', 'mcpAnalyticsTool'],
        '/mcp-analytics/intent-clustering': ['MCPAnalytics', 'mcpAnalyticsIntentClustering'],
    },
    redirects: {
        // `landing=auto` marks "arrived via the bare URL": the scene resolves it to the
        // volume-appropriate default tab, and deep links to /dashboard stay untouched.
        '/mcp-analytics': (_params, searchParams, hashParams) =>
            combineUrl(urls.mcpAnalyticsDashboard(), { ...searchParams, landing: 'auto' }, hashParams).url,
    },
    urls: {
        // Define URL helpers here
        mcpAnalyticsActivity: (): string => '/mcp-analytics/activity',
        mcpAnalyticsDashboard: (): string => '/mcp-analytics/dashboard',
        mcpAnalyticsSessions: (): string => '/mcp-analytics/sessions',
        mcpAnalyticsToolQuality: (): string => '/mcp-analytics/tool-quality',
        mcpAnalyticsTool: (toolName: string): string => `/mcp-analytics/tool-quality/${encodeURIComponent(toolName)}`,
        mcpAnalyticsIntentClustering: (): string => '/mcp-analytics/intent-clustering',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'MCP analytics',
            intents: [ProductKey.AI_OBSERVABILITY],
            category: ProductItemCategory.AI_ENGINEERING,
            visualOrder: 2,
            type: 'mcp_analytics',
            iconType: 'llm_analytics' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-analytics-light)'] as FileSystemIconColor,
            href: urls.mcpAnalyticsDashboard(),
            flag: FEATURE_FLAGS.MCP_ANALYTICS,
            tags: ['beta'],
            sceneKey: 'MCPAnalytics',
        },
    ],
}
