import { connect, kea, path, selectors } from 'kea'

import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'

import { sceneLogic } from '~/scenes/sceneLogic'

export type MCPAnalyticsTab = 'dashboard' | 'sessions' | 'tool-quality'

export const TAB_DESCRIPTIONS: Record<MCPAnalyticsTab, string> = {
    dashboard: 'Overview of your MCP usage.',
    sessions: 'Sessions where users interacted with your MCP tools.',
    'tool-quality': 'Understand how reliably your MCP tools support user workflows.',
}

export const mcpAnalyticsSceneLogic = kea([
    path(['products', 'mcp_analytics', 'frontend', 'mcpAnalyticsSceneLogic']),
    tabAwareScene(),
    connect(() => ({
        values: [sceneLogic, ['sceneKey']],
    })),
    selectors({
        activeTab: [
            (s) => [s.sceneKey],
            (sceneKey: string): MCPAnalyticsTab =>
                sceneKey === 'mcpAnalyticsToolQuality' ? 'tool-quality' : 'dashboard',
        ],
    }),
])
