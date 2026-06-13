import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconSearch, IconX } from '@posthog/icons'
import { type ChartTheme } from '@posthog/quill-charts'
import { Button, InputGroup, InputGroupAddon, InputGroupInput, InputGroupText } from '@posthog/quill-primitives'

import { buildTheme } from 'lib/charts/utils/theme'
import { LinkPrimitive } from 'lib/lemon-ui/Link/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { mcpAnalyticsToolQualityLogic } from './mcpAnalyticsToolQualityLogic'
import { CategoryScopeSelect } from './tool-quality/CategoryScopeSelect'
import { ToolQualityCharts } from './tool-quality/ToolQualityCharts'
import { ToolQualityDateFilter } from './tool-quality/ToolQualityDateFilter'
import { ToolQualityTable } from './tool-quality/ToolQualityTable'

function FilterBar(): JSX.Element {
    const { availableCategories, availableCategoriesLoading, selectedCategories, scopeShare, dateFilter, searchTerm } =
        useValues(mcpAnalyticsToolQualityLogic)
    const { setSelectedCategories, setDateFilter, setSearchTerm } = useActions(mcpAnalyticsToolQualityLogic)

    const hasScope = selectedCategories.length > 0
    const sharePct = scopeShare.pct === null ? null : Math.round(scopeShare.pct * 10) / 10

    return (
        <div className="flex flex-wrap items-center gap-3">
            <div className="min-w-[220px] max-w-[420px] flex-1" data-attr="mcp-tool-quality-category-scope">
                <CategoryScopeSelect
                    categories={availableCategories}
                    value={selectedCategories}
                    loading={availableCategoriesLoading}
                    onChange={setSelectedCategories}
                />
            </div>
            <ToolQualityDateFilter
                dateFrom={dateFilter.dateFrom}
                dateTo={dateFilter.dateTo}
                onChange={(dateFrom, dateTo) => setDateFilter(dateFrom, dateTo)}
            />
            <InputGroup className="w-[220px]">
                <InputGroupAddon align="inline-start">
                    <InputGroupText>
                        <IconSearch />
                    </InputGroupText>
                </InputGroupAddon>
                <InputGroupInput
                    type="search"
                    placeholder="Search tools"
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    data-attr="mcp-tool-quality-search"
                />
            </InputGroup>
            {hasScope && sharePct !== null ? (
                <Tooltip
                    title={`${scopeShare.inScope.toLocaleString()} of ${scopeShare.total.toLocaleString()} MCP tool calls in the last 7 days were in the selected categories`}
                >
                    <div className="text-sm text-muted">
                        <span className="font-semibold text-default">{sharePct}%</span> of MCP usage (last 7d)
                    </div>
                </Tooltip>
            ) : null}
        </div>
    )
}

// Labels the chart section with its current scope: the selected tool (with actions
// to open the full report or clear), or all tools when nothing is selected.
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
    const { isDarkModeOn } = useValues(themeLogic)
    const { timezone } = useValues(teamLogic)

    // buildTheme() reads CSS vars from the DOM; isDarkModeOn is the dep that forces a recompute when
    // the theme flips (it isn't passed as an argument).
    const theme = useMemo<ChartTheme>(() => buildTheme(), [isDarkModeOn])

    return (
        <div className="flex flex-col gap-4" data-quill>
            <FilterBar />
            <ChartsScopeHeader />
            <ToolQualityCharts data={dailyChartData} loading={dailyStatsLoading} theme={theme} timezone={timezone} />
            <ToolQualityTable />
        </div>
    )
}
