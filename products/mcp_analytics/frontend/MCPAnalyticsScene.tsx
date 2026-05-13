import { useValues } from 'kea'
import { router, combineUrl } from 'kea-router'

import { LemonButton, LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SceneExport } from '~/scenes/sceneTypes'

import { MCPAnalyticsDashboard } from './MCPAnalyticsDashboard'
import { MCPAnalyticsTab, TAB_DESCRIPTIONS, mcpAnalyticsSceneLogic } from './mcpAnalyticsSceneLogic'

export const scene: SceneExport = {
    component: MCPAnalyticsScene,
    logic: mcpAnalyticsSceneLogic,
}

const DEFAULT_DOCS_URL = 'https://posthog.com/docs/mcp-analytics/installation'

export function MCPAnalyticsScene(): JSX.Element {
    const { searchParams } = useValues(router)
    const { activeTab } = useValues(mcpAnalyticsSceneLogic)

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
            content: <div>Sessions</div>,
            link: combineUrl(urls.mcpAnalyticsSessions(), searchParams).url,
            'data-attr': 'mcp-analytics-sessions-tab',
        },
        {
            key: 'tool-quality',
            label: 'Tool quality',
            content: <div>Tool quality</div>,
            link: combineUrl(urls.mcpAnalyticsToolQuality(), searchParams).url,
            'data-attr': 'mcp-analytics-tool-quality-tab',
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="MCP analytics"
                description={TAB_DESCRIPTIONS[activeTab]}
                resourceType={{ type: 'llm_analytics' }}
                actions={
                    <LemonButton to={DEFAULT_DOCS_URL} type="secondary" targetBlank size="small">
                        Documentation
                    </LemonButton>
                }
            />
            <LemonTabs activeKey={activeTab} data-attr="mcp-analytics-tabs" tabs={tabs} sceneInset />
        </SceneContent>
    )
}
