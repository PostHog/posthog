import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { type ChartTheme } from '@posthog/quill-charts'
import { Card, CardContent } from '@posthog/quill-primitives'

import { buildTheme } from 'lib/charts/utils/theme'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { formatPercentage } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { formatMs, formatNumber } from './dashboard/formatters'
import { mcpAnalyticsToolQualityLogic } from './mcpAnalyticsToolQualityLogic'
import { ToolQualityCharts } from './tool-quality/ToolQualityCharts'
import { ToolQualityTable } from './tool-quality/ToolQualityTable'

function FilterBar(): JSX.Element {
    const {
        availableCategories,
        availableCategoriesLoading,
        selectedCategories,
        scopeShare,
        selectedTool,
        toolOptions,
        toolRowsLoading,
        dateFilter,
    } = useValues(mcpAnalyticsToolQualityLogic)
    const { setSelectedCategories, setSelectedTool, setDateFilter } = useActions(mcpAnalyticsToolQualityLogic)

    const hasScope = selectedCategories.length > 0
    const sharePct = scopeShare.pct === null ? null : Math.round(scopeShare.pct * 10) / 10

    return (
        <div className="flex flex-wrap items-center gap-3">
            <div className="w-[280px]">
                <LemonInputSelect
                    mode="single"
                    value={selectedTool ? [selectedTool] : []}
                    onChange={(value) => setSelectedTool(value[0] ?? null)}
                    options={toolOptions.map((tool) => ({ key: tool, label: tool }))}
                    loading={toolRowsLoading}
                    placeholder="Drill down into a tool…"
                    data-attr="mcp-tool-quality-tool-select"
                />
            </div>
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
            <DateFilter
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

function ToolStat({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <div className="flex flex-col">
            <span className="text-[10px] uppercase tracking-wider text-secondary">{label}</span>
            <span className="text-base font-semibold leading-tight">{value}</span>
        </div>
    )
}

// Compact summary of the selected tool over the active date range, sourced from
// the already-loaded table row — no extra query.
function SelectedToolStrip(): JSX.Element | null {
    const { selectedTool, selectedRow } = useValues(mcpAnalyticsToolQualityLogic)
    const { setSelectedTool } = useActions(mcpAnalyticsToolQualityLogic)

    if (!selectedTool) {
        return null
    }

    return (
        <Card size="sm">
            <CardContent className="flex flex-wrap items-center gap-x-8 gap-y-3">
                <span className="truncate font-mono text-sm font-semibold" title={selectedTool}>
                    {selectedTool}
                </span>
                <ToolStat label="Calls" value={selectedRow ? formatNumber(selectedRow.total_calls) : '—'} />
                <ToolStat
                    label="Error rate"
                    value={selectedRow ? formatPercentage(selectedRow.error_rate_pct, { compact: true }) : '—'}
                />
                <ToolStat label="p95 latency" value={selectedRow ? formatMs(selectedRow.p95_duration_ms) : '—'} />
                <ToolStat label="p99 latency" value={selectedRow ? formatMs(selectedRow.p99_duration_ms) : '—'} />
                <ToolStat label="Users" value={selectedRow ? formatNumber(selectedRow.users) : '—'} />
                <ToolStat label="Sessions" value={selectedRow ? formatNumber(selectedRow.sessions) : '—'} />
                <div className="ml-auto flex items-center gap-1">
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={urls.mcpAnalyticsTool(selectedTool)}
                        data-attr="mcp-tool-quality-full-report"
                    >
                        Full tool report
                    </LemonButton>
                    <LemonButton
                        size="small"
                        icon={<IconX />}
                        onClick={() => setSelectedTool(null)}
                        tooltip="Clear tool selection"
                        data-attr="mcp-tool-quality-clear-tool"
                    />
                </div>
            </CardContent>
        </Card>
    )
}

export function MCPAnalyticsToolQuality(): JSX.Element {
    const { dailyChartData, dailyStatsLoading, selectedTool } = useValues(mcpAnalyticsToolQualityLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const { timezone } = useValues(teamLogic)

    // buildTheme() reads CSS vars from the DOM; isDarkModeOn is the dep that forces a recompute when
    // the theme flips (it isn't passed as an argument).
    const theme = useMemo<ChartTheme>(() => buildTheme(), [isDarkModeOn])

    return (
        <div className="flex flex-col gap-4" data-quill>
            <FilterBar />
            <SelectedToolStrip />
            {!selectedTool ? (
                <div className="text-xs text-secondary">
                    Trends across all tools in scope — select a tool to drill down.
                </div>
            ) : null}
            <ToolQualityCharts data={dailyChartData} loading={dailyStatsLoading} theme={theme} timezone={timezone} />
            <ToolQualityTable />
        </div>
    )
}
