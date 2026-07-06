import { connect, kea, listeners, path, selectors } from 'kea'
import { combineUrl, router } from 'kea-router'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { sceneLogic } from '~/scenes/sceneLogic'
import { OnboardingStepKey } from '~/types'

import { mcpAnalyticsOnboardingLogic } from './mcpAnalyticsOnboardingLogic'
import type { mcpAnalyticsSceneLogicType } from './mcpAnalyticsSceneLogicType'

export type MCPAnalyticsTab = 'activity' | 'dashboard' | 'sessions' | 'tool-quality' | 'intent-clustering'

export const TAB_DESCRIPTIONS: Record<MCPAnalyticsTab, string> = {
    activity: 'Live feed of tool calls and what agents are trying to do with your MCP server.',
    dashboard: 'Tool call volume, error rates, and latency across your MCP server.',
    sessions: 'Sessions where users interacted with your MCP tools.',
    'tool-quality': 'Understand how reliably your MCP tools support user workflows.',
    'intent-clustering':
        'Cluster semantically similar user intents and see which tools each cluster routes to. Highlights inconsistent routing.',
}

// Per-tab question seeded into PostHog AI so the answer is grounded in what the user is looking at.
export const TAB_AI_PROMPTS: Record<MCPAnalyticsTab, string> = {
    activity:
        'What have agents done with my MCP server recently? Look at the latest $mcp_tool_call events — tools, intents, failures.',
    dashboard:
        "Summarize how agents are using my MCP server from $mcp_tool_call events — top tools, error rates, and what they're trying to do.",
    sessions:
        'What are agents actually trying to do across my MCP sessions? Group the $mcp_intent values on $mcp_tool_call events into themes.',
    'tool-quality':
        'Which of my MCP tools are least reliable? Break down $mcp_tool_call error rate and p95 $mcp_duration_ms by $mcp_tool_name.',
    'intent-clustering':
        "What's the biggest unmet need agents have that my MCP tools don't cover? Look at $mcp_missing_capability and $mcp_intent.",
}

const SCENE_KEY_TO_TAB: Record<string, MCPAnalyticsTab> = {
    mcpAnalyticsActivity: 'activity',
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
    listeners(({ values, cache }) => ({
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
                return
            }
            // Volume decides the default landing tab, once per mount: low-volume projects
            // land on the live activity view, higher-volume ones on the metrics dashboard.
            // Both stay reachable as plain tabs — this never overrides an explicit choice
            // (only the bare dashboard URL redirects) and never flip-flops mid-session.
            if (
                !cache.landingResolved &&
                values.activeTab === 'dashboard' &&
                mcpAnalyticsOnboardingLogic.values.dashboardStage === 'activity'
            ) {
                cache.landingResolved = true
                router.actions.replace(combineUrl(urls.mcpAnalyticsActivity(), router.values.searchParams).url)
            }
            cache.landingResolved = true
        },
    })),
])
