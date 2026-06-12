import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { type ChartTheme } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { mcpAnalyticsToolQualityLogic } from './mcpAnalyticsToolQualityLogic'
import { ToolQualityCharts } from './tool-quality/ToolQualityCharts'
import { ToolQualityDateFilter } from './tool-quality/ToolQualityDateFilter'
import { ToolQualityTable } from './tool-quality/ToolQualityTable'

function FilterBar(): JSX.Element {
    const { availableCategories, availableCategoriesLoading, selectedCategories, scopeShare, dateFilter } =
        useValues(mcpAnalyticsToolQualityLogic)
    const { setSelectedCategories, setDateFilter } = useActions(mcpAnalyticsToolQualityLogic)

    const hasScope = selectedCategories.length > 0
    const sharePct = scopeShare.pct === null ? null : Math.round(scopeShare.pct * 10) / 10

    return (
        <div className="flex flex-wrap items-center gap-3">
            <div className="min-w-[220px] max-w-[420px] flex-1">
                <LemonInputSelect
                    mode="multiple"
                    value={selectedCategories}
                    onChange={setSelectedCategories}
                    options={availableCategories.map((category) => ({ key: category, label: category }))}
                    loading={availableCategoriesLoading}
                    placeholder="All categories"
                    data-attr="mcp-tool-quality-category-scope"
                />
            </div>
            <ToolQualityDateFilter
                dateFrom={dateFilter.dateFrom}
                dateTo={dateFilter.dateTo}
                onChange={(dateFrom, dateTo) => setDateFilter(dateFrom, dateTo)}
            />
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
            <div className="text-xs text-secondary">
                Trends across all tools in scope — select a row above to drill down.
            </div>
        )
    }

    return (
        <div className="flex items-center gap-2">
            <span className="truncate font-mono text-sm font-semibold" title={selectedTool}>
                {selectedTool}
            </span>
            <LemonButton
                type="secondary"
                size="xsmall"
                to={urls.mcpAnalyticsTool(selectedTool)}
                data-attr="mcp-tool-quality-full-report"
            >
                Full tool report
            </LemonButton>
            <LemonButton
                size="xsmall"
                icon={<IconX />}
                onClick={() => setSelectedTool(null)}
                tooltip="Show all tools"
                data-attr="mcp-tool-quality-clear-tool"
            />
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
            <ToolQualityTable />
            <ChartsScopeHeader />
            <ToolQualityCharts data={dailyChartData} loading={dailyStatsLoading} theme={theme} timezone={timezone} />
        </div>
    )
}
