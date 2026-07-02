import { useValues } from 'kea'
import { router, combineUrl } from 'kea-router'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { FeaturePreviewSceneGate } from '~/layout/scenes/components/FeaturePreviewSceneGate'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SceneExport } from '~/scenes/sceneTypes'

import { askPostHogAI } from './askPostHogAI'
import { MCPAnalyticsClustering } from './clustering/MCPAnalyticsClustering'
import { mcpAnalyticsFeaturePreviewGate } from './featurePreviewGate'
import { MCPAnalyticsDashboard } from './MCPAnalyticsDashboard'
import { MCPAnalyticsLoading, MCPAnalyticsOnboarding } from './MCPAnalyticsOnboarding'
import { mcpAnalyticsOnboardingLogic } from './mcpAnalyticsOnboardingLogic'
import {
    MCP_DOCS_URL,
    MCPAnalyticsTab,
    TAB_AI_PROMPTS,
    TAB_DESCRIPTIONS,
    mcpAnalyticsSceneLogic,
} from './mcpAnalyticsSceneLogic'
import { MCPAnalyticsSceneMenuBar } from './MCPAnalyticsSceneMenuBar'
import { MCPAnalyticsToolQuality } from './MCPAnalyticsToolQuality'
import { MCPSessionsPlaylist } from './sessions/MCPSessionsPlaylist'

export const scene: SceneExport = {
    component: MCPAnalyticsScene,
    logic: mcpAnalyticsSceneLogic,
}

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
    const { onboardingState, signals } = useValues(mcpAnalyticsOnboardingLogic)

    const tabs: LemonTab<MCPAnalyticsTab>[] = [
        {
            key: 'dashboard',
            label: 'Dashboard',
            content: <MCPAnalyticsDashboard />,
            link: combineUrl(urls.mcpAnalyticsDashboard(), searchParams).url,
            'data-attr': 'mcp-analytics-dashboard-tab',
        },
        {
            key: 'sessions',
            label: 'Sessions',
            content: <MCPSessionsPlaylist />,
            link: combineUrl(urls.mcpAnalyticsSessions(), searchParams).url,
            'data-attr': 'mcp-analytics-sessions-tab',
        },
        {
            key: 'tool-quality',
            label: 'Tool quality',
            content: <MCPAnalyticsToolQuality />,
            link: combineUrl(urls.mcpAnalyticsToolQuality(), searchParams).url,
            'data-attr': 'mcp-analytics-tool-quality-tab',
        },
        {
            key: 'intent-clustering',
            label: 'Intent clustering',
            content: <MCPAnalyticsClustering />,
            link: combineUrl(urls.mcpAnalyticsIntentClustering(), searchParams).url,
            'data-attr': 'mcp-analytics-intent-clustering-tab',
        },
    ]

    return (
        <SceneContent>
            <MCPAnalyticsSceneMenuBar />
            <SceneTitleSection
                name="MCP analytics"
                description={onboardingState === 'onboarded' ? TAB_DESCRIPTIONS[activeTab] : null}
                resourceType={{ type: 'llm_analytics' }}
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
            {/* `signals === null` means we don't know yet — still loading, or a transient
                query failure. Hold the skeleton rather than falling through to the empty
                dashboard (the very state this onboarding exists to avoid); the 20s poll retries. */}
            {signals === null ? (
                <MCPAnalyticsLoading />
            ) : onboardingState && onboardingState !== 'onboarded' ? (
                <MCPAnalyticsOnboarding state={onboardingState} />
            ) : (
                <LemonTabs activeKey={activeTab} data-attr="mcp-analytics-tabs" tabs={tabs} sceneInset />
            )}
        </SceneContent>
    )
}
