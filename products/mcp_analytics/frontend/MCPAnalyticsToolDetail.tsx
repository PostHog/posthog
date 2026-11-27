import { BindLogic, useActions, useValues } from 'kea'
import { Suspense } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SceneExport } from '~/scenes/sceneTypes'

import { McpDateFilter } from './components/McpDateFilter'
import { McpSharedFilters } from './components/McpSharedFilters'
import { MCPAnalyticsToolDetailLogicProps, mcpAnalyticsToolDetailLogic } from './mcpAnalyticsToolDetailLogic'
import { mcpToolQualityUrlWithDates } from './mcpAnalyticsToolQualityLogic'
import { mcpToolDetailSceneLogic } from './mcpToolDetailSceneLogic'
import { MCPToolReport } from './MCPToolReport'

const LegacyMCPAnalyticsToolDetail = lazyWithRetry(() =>
    import('./legacy/MCPAnalyticsToolDetail').then((m) => ({ default: m.MCPAnalyticsToolDetail }))
)

export const scene: SceneExport<MCPAnalyticsToolDetailLogicProps> = {
    component: MCPAnalyticsToolDetailScene,
    logic: mcpToolDetailSceneLogic,
    paramsToProps: ({ params: { toolName } }) => ({
        toolName: decodeURIComponent(toolName ?? ''),
    }),
}

function MCPAnalyticsToolDetailScene(): JSX.Element {
    const { toolName } = useValues(mcpToolDetailSceneLogic)
    const redesign = useFeatureFlag('MCP_ANALYTICS_REDESIGN')
    if (!redesign) {
        return (
            <Suspense fallback={null}>
                <LegacyMCPAnalyticsToolDetail toolName={toolName} />
            </Suspense>
        )
    }
    return (
        <BindLogic logic={mcpAnalyticsToolDetailLogic} props={{ toolName }}>
            <MCPAnalyticsToolDetail />
        </BindLogic>
    )
}

export function MCPAnalyticsToolDetail(): JSX.Element {
    const {
        toolName,
        dateFilter,
        pinnedInterval,
        summaryLoading,
        descriptionsLoading,
        dailyStatsLoading,
        journeyLoading,
        examplesLoading,
        byHarnessRowsLoading,
        topUserRowsLoading,
    } = useValues(mcpAnalyticsToolDetailLogic)
    const { setDateFilter, loadAllSections } = useActions(mcpAnalyticsToolDetailLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name={toolName}
                description={null}
                resourceType={{ type: 'mcp_analytics' }}
                forceBackTo={{
                    name: 'Tool quality',
                    path: mcpToolQualityUrlWithDates(dateFilter, pinnedInterval),
                    key: 'mcp-analytics-tool-quality',
                }}
            />

            <div className="flex flex-wrap items-center gap-3 px-4 pb-2">
                <McpSharedFilters
                    pageKey="mcp-tool-detail"
                    dataAttrPrefix="mcp-tool-detail"
                    onRefresh={loadAllSections}
                    refreshing={
                        summaryLoading ||
                        descriptionsLoading ||
                        dailyStatsLoading ||
                        journeyLoading ||
                        examplesLoading ||
                        byHarnessRowsLoading ||
                        topUserRowsLoading
                    }
                >
                    <McpDateFilter
                        dateFrom={dateFilter.dateFrom}
                        dateTo={dateFilter.dateTo}
                        onChange={setDateFilter}
                        dataAttr="mcp-tool-detail-date-filter"
                    />
                </McpSharedFilters>
            </div>

            <MCPToolReport />
        </SceneContent>
    )
}
