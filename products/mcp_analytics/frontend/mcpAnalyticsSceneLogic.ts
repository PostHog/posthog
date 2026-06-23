import { connect, kea, path, selectors } from 'kea'

import { sceneLogic } from '~/scenes/sceneLogic'

import type { mcpAnalyticsSceneLogicType } from './mcpAnalyticsSceneLogicType'

export type MCPAnalyticsTab = 'dashboard' | 'sessions' | 'tool-quality' | 'intent-clustering'

export const TAB_DESCRIPTIONS: Record<MCPAnalyticsTab, string> = {
    dashboard: 'Overview of your MCP usage.',
    sessions: 'Sessions where users interacted with your MCP tools.',
    'tool-quality': 'Understand how reliably your MCP tools support user workflows.',
    'intent-clustering':
        'Cluster semantically similar user intents and see which tools each cluster routes to. Highlights inconsistent routing.',
}

const SCENE_KEY_TO_TAB: Record<string, MCPAnalyticsTab> = {
    mcpAnalyticsDashboard: 'dashboard',
    mcpAnalyticsSessions: 'sessions',
    mcpAnalyticsToolQuality: 'tool-quality',
    mcpAnalyticsIntentClustering: 'intent-clustering',
}

export const mcpAnalyticsSceneLogic = kea<mcpAnalyticsSceneLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'mcpAnalyticsSceneLogic']),
    connect(() => ({
        values: [sceneLogic, ['sceneKey']],
    })),
    selectors({
        activeTab: [
            (s) => [s.sceneKey],
            (sceneKey: string): MCPAnalyticsTab => SCENE_KEY_TO_TAB[sceneKey] ?? 'dashboard',
        ],
    }),
])
