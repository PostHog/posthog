import { connect, kea, path, selectors } from 'kea'

import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'

import { sceneLogic } from '~/scenes/sceneLogic'

import type { mcpAnalyticsSceneLogicType } from './mcpAnalyticsSceneLogicType'

export type MCPAnalyticsTab = 'dashboard' | 'sessions' | 'tools' | 'tasks'

export const TAB_DESCRIPTIONS: Record<MCPAnalyticsTab, string> = {
    dashboard: 'Overview of your MCP usage.',
    sessions: 'Sessions where users interacted with your MCP tools.',
    tools: 'Understand how reliably your MCP tools support user workflows.',
    tasks: 'Groups of similar agent goals, with the tools each group used and where they failed.',
}

const SCENE_KEY_TO_TAB: Record<string, MCPAnalyticsTab> = {
    mcpAnalyticsDashboard: 'dashboard',
    mcpAnalyticsSessions: 'sessions',
    mcpAnalyticsTools: 'tools',
    mcpAnalyticsTasks: 'tasks',
}

export const mcpAnalyticsSceneLogic = kea<mcpAnalyticsSceneLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'mcpAnalyticsSceneLogic']),
    tabAwareScene(),
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
