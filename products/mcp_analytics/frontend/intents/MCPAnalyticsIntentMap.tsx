import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SceneExport } from '~/scenes/sceneTypes'

import { McpDateFilter } from '../components/McpDateFilter'
import { mcpDateSearchParams, mcpToolReportUrl } from '../mcpAnalyticsToolQualityLogic'
import { intentMapLogic } from './intentMapLogic'
import { IntentScatterPlot } from './IntentScatterPlot'
import { IntentTopicsScopeNote } from './IntentTopicsScopeNote'
import { TopicPanel } from './TopicPanel'

export const scene: SceneExport = {
    component: MCPAnalyticsIntentMap,
    logic: intentMapLogic,
}

export function MCPAnalyticsIntentMap(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { tool, topicId, dateFilter, dateRangeLabel, isZoomed } = useValues(intentMapLogic)
    const { setTool, setTopicId, setDateFilter, setZoom } = useActions(intentMapLogic)

    if (!featureFlags[FEATURE_FLAGS.MCP_ANALYTICS_INTENT_TOPICS]) {
        return <NotFound object="page" />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Intent map"
                description="Every agent intent, embedded and grouped into topics. Bubbles are topics; click one to see its intents, drag to zoom."
                resourceType={{ type: 'mcp_analytics' }}
                forceBackTo={
                    tool
                        ? { name: tool, path: mcpToolReportUrl(tool, dateFilter), key: 'mcp-analytics-tool' }
                        : {
                              name: 'MCP analytics',
                              path: combineUrl(urls.mcpAnalyticsDashboard(), mcpDateSearchParams(dateFilter)).url,
                              key: 'mcp-analytics-dashboard',
                          }
                }
            />
            <div className="flex flex-wrap items-center gap-2 px-4">
                <McpDateFilter
                    dateFrom={dateFilter.dateFrom}
                    dateTo={dateFilter.dateTo}
                    onChange={setDateFilter}
                    dataAttr="mcp-intent-map-date"
                />
                <span className="text-xs text-secondary">{dateRangeLabel}</span>
                {tool ? (
                    <LemonTag type="highlight" closable onClose={() => setTool(null)}>
                        Tool: <span translate="no">{tool}</span>
                    </LemonTag>
                ) : null}
                {topicId ? (
                    <LemonTag type="highlight" closable onClose={() => setTopicId(null)}>
                        One topic
                    </LemonTag>
                ) : null}
                {isZoomed ? (
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        onClick={() => setZoom(null)}
                        data-attr="mcp-intent-map-reset-zoom"
                    >
                        Reset zoom
                    </LemonButton>
                ) : null}
                <IntentTopicsScopeNote
                    filtersIgnored={false}
                    dateFrom={dateFilter.dateFrom}
                    dateTo={dateFilter.dateTo}
                />
            </div>
            {/* Both cards get the same fixed height: the panel scrolls inside it, so a long topic list
                cannot stretch the chart beyond the viewport. */}
            <div className="grid grid-cols-1 gap-4 px-4 pb-4 @min-[64rem]/main-content:grid-cols-[2fr_1fr]" data-quill>
                <div className="h-[36rem] rounded border bg-bg-light p-2">
                    <IntentScatterPlot />
                </div>
                <div className="h-[36rem] min-h-0 overflow-hidden rounded border bg-bg-light p-3">
                    <TopicPanel />
                </div>
            </div>
        </SceneContent>
    )
}
