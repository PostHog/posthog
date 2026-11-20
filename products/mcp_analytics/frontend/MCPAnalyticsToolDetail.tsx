import { useActions, useValues } from 'kea'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SceneExport } from '~/scenes/sceneTypes'

import { McpDateFilter } from './components/McpDateFilter'
import { McpSharedFilters } from './components/McpSharedFilters'
import { MCPAnalyticsToolDetailLogicProps, mcpAnalyticsToolDetailLogic } from './mcpAnalyticsToolDetailLogic'
import { mcpToolQualityUrlWithDates } from './mcpAnalyticsToolQualityLogic'
import { MCPToolReport } from './MCPToolReport'

export const scene: SceneExport<MCPAnalyticsToolDetailLogicProps> = {
    component: MCPAnalyticsToolDetail,
    logic: mcpAnalyticsToolDetailLogic,
    paramsToProps: ({ params: { toolName } }) => ({
        toolName: decodeURIComponent(toolName ?? ''),
    }),
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
