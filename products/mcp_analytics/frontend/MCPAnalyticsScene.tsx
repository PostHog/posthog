import { useValues } from 'kea'
import { router, combineUrl } from 'kea-router'
import React from 'react'

import { LemonButton, LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SceneExport } from '~/scenes/sceneTypes'

export const scene: SceneExport = {
    component: MCPAnalyticsScene,
}

type MCPAnalyticsTab = 'dashboard' | 'sessions'

const TAB_DESCRIPTIONS: Record<MCPAnalyticsTab, string> = {
    dashboard: 'Overview of your MCP usage.',
    sessions: 'Sessions where users interacted with your MCP tools.',
}

const DEFAULT_DOCS_URL = 'https://posthog.com/docs/mcp-analytics/installation'

export function MCPAnalyticsScene(): JSX.Element {
    const { searchParams, location } = useValues(router)
    const activeTab: MCPAnalyticsTab = location.pathname.endsWith('/sessions') ? 'sessions' : 'dashboard'

    const tabs: LemonTab<MCPAnalyticsTab>[] = [
        {
            key: 'dashboard',
            label: 'Dashboard',
            content: <div>ABC</div>,
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
