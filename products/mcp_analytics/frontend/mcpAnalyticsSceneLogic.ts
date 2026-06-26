import { connect, kea, listeners, path, selectors } from 'kea'
import { router } from 'kea-router'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { sceneLogic } from '~/scenes/sceneLogic'
import { OnboardingStepKey } from '~/types'

import { mcpAnalyticsOnboardingLogic } from './mcpAnalyticsOnboardingLogic'
import type { mcpAnalyticsSceneLogicType } from './mcpAnalyticsSceneLogicType'

export type MCPAnalyticsTab = 'dashboard' | 'sessions' | 'tool-quality' | 'intent-clustering'

export const TAB_DESCRIPTIONS: Record<MCPAnalyticsTab, string> = {
    dashboard: 'Tool call volume, error rates, and latency across your MCP server.',
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
        values: [
            sceneLogic,
            ['sceneKey'],
            mcpAnalyticsOnboardingLogic,
            ['onboardingState'],
            teamLogic,
            ['currentTeam'],
        ],
    })),
    selectors({
        activeTab: [
            (s) => [s.sceneKey],
            (sceneKey: string): MCPAnalyticsTab => SCENE_KEY_TO_TAB[sceneKey] ?? 'dashboard',
        ],
    }),
    listeners(({ values }) => ({
        // Send never-set-up projects straight into the polished onboarding flow,
        // rather than the bare in-scene card. Guarded on `has_completed_onboarding_for`
        // so the post-onboarding return to the dashboard doesn't bounce back here —
        // once they've been through setup we let the in-scene "waiting" state show.
        [mcpAnalyticsOnboardingLogic.actionTypes.loadSignalsSuccess]: () => {
            const completed = values.currentTeam?.has_completed_onboarding_for?.[ProductKey.MCP_ANALYTICS]
            if (values.onboardingState === 'not-instrumented' && !completed) {
                router.actions.replace(
                    urls.onboarding({ productKey: ProductKey.MCP_ANALYTICS, stepKey: OnboardingStepKey.INSTALL })
                )
            }
        },
    })),
])
