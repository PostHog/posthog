import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { Button } from '@posthog/quill-primitives'

import { useChartTheme } from 'lib/charts/hooks'
import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'
import { LinkPrimitive } from 'lib/lemon-ui/Link/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { McpDateFilter } from './components/McpDateFilter'
import { mcpAnalyticsToolQualityLogic } from './mcpAnalyticsToolQualityLogic'
import { ToolQualityCharts } from './tool-quality/ToolQualityCharts'
import { ToolQualityTable } from './tool-quality/ToolQualityTable'

function FilterBar(): JSX.Element {
    const { availableCategories, selectedCategories, scopeShare, dateFilter, dateRangeLabel } =
        useValues(mcpAnalyticsToolQualityLogic)
    const { setSelectedCategories, setDateFilter } = useActions(mcpAnalyticsToolQualityLogic)

    const hasScope = selectedCategories.length > 0
    const sharePct = scopeShare.pct === null ? null : Math.round(scopeShare.pct * 10) / 10

    return (
        <div className="flex flex-wrap items-center gap-3">
            <div className="min-w-[220px] max-w-[420px] flex-1">
                <TagsCombobox
                    options={availableCategories}
                    value={selectedCategories}
                    onChange={setSelectedCategories}
                    placeholder="All categories"
                    allowCustomValues={false}
                    dataAttr="mcp-tool-quality-category-scope"
                />
            </div>
            <McpDateFilter
                dateFrom={dateFilter.dateFrom}
                dateTo={dateFilter.dateTo}
                onChange={(dateFrom, dateTo) => setDateFilter(dateFrom, dateTo)}
                dataAttr="mcp-tool-quality-date-filter"
            />
            {hasScope && sharePct !== null ? (
                <Tooltip
                    title={`${scopeShare.inScope.toLocaleString()} of ${scopeShare.total.toLocaleString()} MCP tool calls were in the selected categories (${dateRangeLabel})`}
                >
                    <div className="text-sm text-muted">
                        <span className="font-semibold text-default">{sharePct}%</span> of MCP usage ({dateRangeLabel})
                    </div>
                </Tooltip>
            ) : null}
        </div>
    )
}

function ChartsScopeHeader(): JSX.Element {
    const { selectedTool } = useValues(mcpAnalyticsToolQualityLogic)
    const { setSelectedTool } = useActions(mcpAnalyticsToolQualityLogic)

    if (!selectedTool) {
        return (
            <div className="text-sm text-secondary">
                Trends across all tools in scope — select a row above to drill down.
            </div>
        )
    }

    return (
        <div className="flex items-center gap-2">
            <span className="shrink-0 text-sm text-secondary">Trends for</span>
            <span className="max-w-[28rem] truncate font-mono text-sm font-semibold" title={selectedTool}>
                {selectedTool}
            </span>
            <Button
                variant="outline"
                size="sm"
                render={<LinkPrimitive to={urls.mcpAnalyticsTool(selectedTool)} />}
                data-attr="mcp-tool-quality-full-report"
            >
                Full tool report
            </Button>
            <Button
                variant="link-muted"
                size="icon-sm"
                onClick={() => setSelectedTool(null)}
                title="Show all tools"
                data-attr="mcp-tool-quality-clear-tool"
            >
                <IconX />
            </Button>
        </div>
    )
}

export function MCPAnalyticsToolQuality(): JSX.Element {
    const { dailyChartData, dailyStatsLoading } = useValues(mcpAnalyticsToolQualityLogic)
    const { timezone } = useValues(teamLogic)

    const theme = useChartTheme()

    return (
        <div className="flex flex-col gap-4" data-quill>
            <FilterBar />
            <ChartsScopeHeader />
            <ToolQualityCharts data={dailyChartData} loading={dailyStatsLoading} theme={theme} timezone={timezone} />
            <ToolQualityTable />
        </div>
    )
}
