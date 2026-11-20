import { useActions, useValues } from 'kea'

import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'

import { McpDateFilter } from './components/McpDateFilter'
import { McpSharedFilters } from './components/McpSharedFilters'
import { mcpAnalyticsToolQualityLogic, mcpToolReportUrl } from './mcpAnalyticsToolQualityLogic'
import { ToolQualityTable } from './tool-quality/ToolQualityTable'
import { ToolQualityTiles } from './tool-quality/ToolQualityTiles'
import { ToolReportDrawer } from './tool-quality/ToolReportDrawer'

export function MCPAnalyticsToolQuality(): JSX.Element {
    const {
        dailyStatsLoading,
        dateFilter,
        toolRowsPageLoading,
        searchTerm,
        selectedTool,
        selectedToolPosition,
        previousTool,
        nextTool,
        pinnedInterval,
    } = useValues(mcpAnalyticsToolQualityLogic)
    const { setDateFilter, reloadAll, setSearchTerm, setSelectedTool } = useActions(mcpAnalyticsToolQualityLogic)

    return (
        <div className="flex flex-col gap-4">
            <McpSharedFilters
                pageKey="mcp-tool-quality"
                dataAttrPrefix="mcp-tool-quality"
                onRefresh={reloadAll}
                refreshing={dailyStatsLoading || toolRowsPageLoading}
                hasPageFilters={!!searchTerm}
                onClearPageFilters={() => setSearchTerm('')}
            >
                <AnalyticsSearchInput
                    value={searchTerm}
                    onChange={setSearchTerm}
                    label="Search tools"
                    placeholder="Search tools"
                    dataAttr="mcp-tool-quality-search"
                    className="max-w-64 min-w-32 flex-[1_1_8rem]"
                />
                <McpDateFilter
                    dateFrom={dateFilter.dateFrom}
                    dateTo={dateFilter.dateTo}
                    onChange={setDateFilter}
                    dataAttr="mcp-tool-quality-date-filter"
                />
            </McpSharedFilters>
            <div className="flex flex-col gap-4" data-quill>
                <ToolQualityTiles />
                <ToolQualityTable />
            </div>
            <ToolReportDrawer
                tool={selectedTool}
                position={selectedToolPosition}
                previousTool={previousTool}
                nextTool={nextTool}
                onOpen={setSelectedTool}
                fullPageHref={selectedTool ? mcpToolReportUrl(selectedTool, dateFilter, pinnedInterval) : ''}
                dataAttr="mcp-tool-quality-drawer"
            />
        </div>
    )
}
