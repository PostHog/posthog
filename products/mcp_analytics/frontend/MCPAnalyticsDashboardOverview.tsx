import { useActions, useValues } from 'kea'

import { useChartTheme } from 'lib/charts/hooks'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'

import { McpDateFilter } from './components/McpDateFilter'
import { McpSharedFilters } from './components/McpSharedFilters'
import { ActivityChart } from './dashboard/ActivityChart'
import { HarnessBarChart } from './dashboard/HarnessBarChart'
import { KpiTiles } from './dashboard/KpiTiles'
import { ModelBarChart } from './dashboard/ModelBarChart'
import { NotableSessionsTable } from './dashboard/NotableSessionsTable'
import { RecentToolCallsCard } from './dashboard/RecentToolCallsCard'
import { ToolErrorRateChart } from './dashboard/ToolErrorRateChart'
import { ToolUsageChart } from './dashboard/ToolUsageChart'
import { MCP_ANALYTICS_DASHBOARD_FEEDBACK_PROMPT } from './feedback/constants'
import { MCPAnalyticsFeedbackPrompt } from './feedback/MCPAnalyticsFeedbackPrompt'
import { MCPAnalyticsFirstLook } from './firstLook/MCPAnalyticsFirstLook'
import { mcpDashboardOverviewLogic } from './mcpDashboardOverviewLogic'

export function MCPAnalyticsDashboardOverview(): JSX.Element {
    const {
        kpis,
        kpisLoading,
        users,
        usersLoading,
        intentClusterCount,
        notableSessions,
        sessionRowsLoading,
        harnessRows,
        harnessRowsLoading,
        modelRows,
        modelRowsLoading,
        hasModelData,
        dailyActivity,
        activityRowsLoading,
        activityIncompleteTail,
        kpiIncompleteTail,
        toolDailySeries,
        toolDailyRowsLoading,
        toolRows,
        toolRowsLoading,
        dateFilter,
        interval,
        queryFilters,
        canShowFeedback,
        feedbackContextKey,
    } = useValues(mcpDashboardOverviewLogic)
    const { setDateFilter, reloadAll, markFilterInteraction } = useActions(mcpDashboardOverviewLogic)
    const { timezone } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const theme = useChartTheme()

    return (
        <div className="@container/mcp-overview flex min-w-0 flex-col gap-6">
            <McpSharedFilters
                pageKey="mcp-dashboard-overview"
                dataAttrPrefix="mcp-dashboard"
                onRefresh={reloadAll}
                refreshing={
                    kpisLoading ||
                    usersLoading ||
                    sessionRowsLoading ||
                    harnessRowsLoading ||
                    modelRowsLoading ||
                    activityRowsLoading ||
                    toolDailyRowsLoading ||
                    toolRowsLoading
                }
            >
                <McpDateFilter
                    dateFrom={dateFilter.dateFrom}
                    dateTo={dateFilter.dateTo}
                    onChange={(dateFrom, dateTo) => {
                        setDateFilter(dateFrom, dateTo)
                        markFilterInteraction()
                    }}
                    dataAttr="mcp-dashboard-date-filter"
                />
            </McpSharedFilters>
            <MCPAnalyticsFeedbackPrompt
                contextKey={feedbackContextKey}
                eligible={canShowFeedback}
                prompt={MCP_ANALYTICS_DASHBOARD_FEEDBACK_PROMPT}
            />
            <MCPAnalyticsFirstLook />
            <section className="flex min-w-0 flex-col gap-4" data-quill>
                <h2 className="mb-4 text-xl font-semibold text-primary">Key metrics</h2>
                <KpiTiles
                    kpis={kpis}
                    users={users}
                    intentClusterCount={intentClusterCount}
                    kpisLoading={kpisLoading}
                    usersLoading={usersLoading}
                    showIntentClusters={!!featureFlags[FEATURE_FLAGS.MCP_ANALYTICS_INTENT_ROUTING]}
                    theme={theme}
                    interval={interval}
                    incompleteTail={kpiIncompleteTail}
                />
            </section>
            <section className="flex min-w-0 flex-col gap-4" data-quill>
                <h2 className="mb-4 text-xl font-semibold text-primary">Usage</h2>
                <div className="flex min-w-0 flex-col gap-4">
                    <div className="grid min-w-0 grid-cols-1 gap-4 @min-[64rem]/mcp-overview:grid-cols-2">
                        <ActivityChart
                            daily={dailyActivity}
                            loading={activityRowsLoading}
                            theme={theme}
                            timezone={timezone}
                            interval={interval}
                            incompleteTail={activityIncompleteTail}
                        />
                        <ToolUsageChart
                            data={toolDailySeries}
                            loading={toolDailyRowsLoading}
                            theme={theme}
                            timezone={timezone}
                            interval={interval}
                        />
                    </div>
                    <div
                        className={cn(
                            'grid min-w-0 grid-cols-1 gap-4',
                            hasModelData && '@min-[48rem]/mcp-overview:grid-cols-2'
                        )}
                    >
                        <HarnessBarChart rows={harnessRows} loading={harnessRowsLoading} theme={theme} />
                        {hasModelData ? <ModelBarChart rows={modelRows} theme={theme} filters={queryFilters} /> : null}
                    </div>
                </div>
            </section>
            <section className="flex min-w-0 flex-col gap-4" data-quill>
                <h2 className="mb-0 text-xl font-semibold text-primary">Reliability</h2>
                <div className="grid min-w-0 grid-cols-1 gap-4 @min-[64rem]/mcp-overview:grid-cols-2">
                    <ToolErrorRateChart rows={toolRows} loading={toolRowsLoading} theme={theme} />
                    <NotableSessionsTable sessions={notableSessions} loading={sessionRowsLoading} />
                </div>
            </section>
            <RecentToolCallsCard filters={queryFilters} />
        </div>
    )
}
