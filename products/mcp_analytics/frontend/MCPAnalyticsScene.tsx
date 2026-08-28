import { useValues } from 'kea'
import { router, combineUrl } from 'kea-router'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonTab, LemonTabs, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { FeaturePreviewSceneGate } from '~/layout/scenes/components/FeaturePreviewSceneGate'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { SceneExport } from '~/scenes/sceneTypes'

import { askPostHogAI } from './askPostHogAI'
import { MCPAnalyticsClustering } from './clustering/MCPAnalyticsClustering'
import { MCPAnalyticsActivityDashboard } from './earlyData/MCPAnalyticsEarlyData'
import { mcpAnalyticsEmptyState } from './emptyState/mcpAnalyticsEmptyState'
import { mcpAnalyticsFeaturePreviewGate } from './featurePreviewGate'
import { MCPAnalyticsDashboard } from './MCPAnalyticsDashboard'
import { mcpAnalyticsOnboardingLogic } from './mcpAnalyticsOnboardingLogic'
import { MCPAnalyticsTab, TAB_AI_PROMPTS, TAB_DESCRIPTIONS, mcpAnalyticsSceneLogic } from './mcpAnalyticsSceneLogic'
import { MCPAnalyticsSceneMenuBar } from './MCPAnalyticsSceneMenuBar'
import { MCPAnalyticsToolQuality } from './MCPAnalyticsToolQuality'
import { MCPAnalyticsNotifications } from './notifications/MCPAnalyticsNotifications'
import { mcpAnalyticsNotificationsLogic } from './notifications/mcpAnalyticsNotificationsLogic'
import { MCPSessionsPlaylist } from './sessions/MCPSessionsPlaylist'

export const scene: SceneExport = {
    component: MCPAnalyticsScene,
    logic: mcpAnalyticsSceneLogic,
    productKey: ProductKey.MCP_ANALYTICS,
    emptyState: mcpAnalyticsEmptyState,
}

const MCP_DOCS_URL = 'https://posthog.com/docs/mcp-analytics/installation'

export function MCPAnalyticsScene(): JSX.Element {
    return (
        <FeaturePreviewSceneGate config={mcpAnalyticsFeaturePreviewGate}>
            <MCPAnalyticsSceneContent />
        </FeaturePreviewSceneGate>
    )
}

function MCPAnalyticsSceneContent(): JSX.Element {
    const { searchParams } = useValues(router)
    const { activeTab } = useValues(mcpAnalyticsSceneLogic)
    const { onboardingState } = useValues(mcpAnalyticsOnboardingLogic)
    const { notificationCount } = useValues(mcpAnalyticsNotificationsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const intentRoutingEnabled = !!featureFlags[FEATURE_FLAGS.MCP_ANALYTICS_INTENT_ROUTING]

    if (activeTab === 'intent-clustering' && !intentRoutingEnabled) {
        return <NotFound object="page" />
    }

    // landing is a one-shot redirect marker, while search is Sessions-only.
    // The date range stays shared across every tab.
    const { landing: _landing, ...tabParams } = searchParams
    const { search: _search, ...sharedParams } = tabParams

    const activityTab: LemonTab<MCPAnalyticsTab> = {
        key: 'activity',
        label: 'Activity',
        content: <MCPAnalyticsActivityDashboard />,
        link: combineUrl(urls.mcpAnalyticsActivity(), sharedParams).url,
        'data-attr': 'mcp-analytics-activity-tab',
    }
    const dashboardTab: LemonTab<MCPAnalyticsTab> = {
        key: 'dashboard',
        label: 'Dashboard',
        content: <MCPAnalyticsDashboard />,
        link: combineUrl(urls.mcpAnalyticsDashboard(), sharedParams).url,
        'data-attr': 'mcp-analytics-dashboard-tab',
    }

    const tabs: LemonTab<MCPAnalyticsTab>[] = [
        dashboardTab,
        activityTab,
        {
            key: 'sessions',
            label: 'Sessions',
            content: <MCPSessionsPlaylist />,
            link: combineUrl(urls.mcpAnalyticsSessions(), tabParams).url,
            'data-attr': 'mcp-analytics-sessions-tab',
        },
        {
            key: 'tool-quality',
            label: 'Tool quality',
            content: <MCPAnalyticsToolQuality />,
            link: combineUrl(urls.mcpAnalyticsToolQuality(), sharedParams).url,
            'data-attr': 'mcp-analytics-tool-quality-tab',
        },
        ...(intentRoutingEnabled
            ? [
                  {
                      key: 'intent-clustering' as const,
                      label: 'Intent clustering',
                      content: <MCPAnalyticsClustering />,
                      link: combineUrl(urls.mcpAnalyticsIntentClustering(), sharedParams).url,
                      'data-attr': 'mcp-analytics-intent-clustering-tab',
                  },
              ]
            : []),
        {
            key: 'notifications',
            label: (
                <span className="flex items-center gap-1.5">
                    Notifications
                    {notificationCount > 0 && (
                        <LemonTag type="completion" size="small">
                            {notificationCount}
                        </LemonTag>
                    )}
                </span>
            ),
            content: <MCPAnalyticsNotifications />,
            link: combineUrl(urls.mcpAnalyticsNotifications(), sharedParams).url,
            'data-attr': 'mcp-analytics-notifications-tab',
        },
    ]

    return (
        <SceneContent>
            <MCPAnalyticsSceneMenuBar />
            <SceneTitleSection
                name="MCP analytics"
                description={onboardingState === 'onboarded' ? TAB_DESCRIPTIONS[activeTab] : null}
                resourceType={{ type: 'mcp_analytics' }}
                actions={
                    <>
                        {onboardingState === 'onboarded' && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconSparkles />}
                                onClick={() => askPostHogAI(TAB_AI_PROMPTS[activeTab])}
                                data-attr="mcp-analytics-ask-ai"
                            >
                                Ask PostHog AI
                            </LemonButton>
                        )}
                        <LemonButton to={MCP_DOCS_URL} type="secondary" targetBlank size="small">
                            Documentation
                        </LemonButton>
                    </>
                }
            />

            {/* Loading and pre-data states are handled by the app-shell empty-state gate
                (see `emptyState` on the SceneExport) — by the time this renders, either
                tool calls exist or the user explicitly skipped setup. */}
            <LemonTabs activeKey={activeTab} data-attr="mcp-analytics-tabs" tabs={tabs} sceneInset />
        </SceneContent>
    )
}
