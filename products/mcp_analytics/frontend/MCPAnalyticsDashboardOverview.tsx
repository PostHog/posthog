import { useActions, useValues } from 'kea'
import { Children, type ReactNode } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { useChartTheme } from 'lib/charts/hooks'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'

import { MCPDashboardSection } from '~/queries/schema/schema-general'

import { McpDateFilter } from './components/McpDateFilter'
import { McpSharedFilters } from './components/McpSharedFilters'
import { ActivityChart } from './dashboard/ActivityChart'
import { MCP_DASHBOARD_CARDS } from './dashboard/dashboardCards'
import { DashboardCardsMenu } from './dashboard/DashboardCardsMenu'
import { HarnessBarChart } from './dashboard/HarnessBarChart'
import { KpiTiles } from './dashboard/KpiTiles'
import { mcpDashboardCardsLogic } from './dashboard/mcpDashboardCardsLogic'
import { ModelBarChart } from './dashboard/ModelBarChart'
import { NotableSessionsTable } from './dashboard/NotableSessionsTable'
import { ProtocolVersionStrip } from './dashboard/ProtocolVersionStrip'
import { RecentToolCallsCard } from './dashboard/RecentToolCallsCard'
import { ToolErrorRateChart } from './dashboard/ToolErrorRateChart'
import { ToolLatencyChart } from './dashboard/ToolLatencyChart'
import { ToolUsageChart } from './dashboard/ToolUsageChart'
import { MCP_ANALYTICS_DASHBOARD_FEEDBACK_PROMPT } from './feedback/constants'
import { MCPAnalyticsFeedbackPrompt } from './feedback/MCPAnalyticsFeedbackPrompt'
import { MCPAnalyticsFirstLook } from './firstLook/MCPAnalyticsFirstLook'
import { mcpToolQualityUrlWithDates } from './mcpAnalyticsToolQualityLogic'
import {
    mcpDashboardOverviewLogic,
    rankedToolsEmptyMessage,
    rankToolsByErrorRate,
    rankToolsByP95,
    slowestToolsEmptyMessage,
} from './mcpDashboardOverviewLogic'

export function MCPAnalyticsDashboardOverview(): JSX.Element {
    const {
        dashboardLoading,
        headlineKpis,
        periodTotals,
        intentClusterCount,
        notableSessions,
        harnessRows,
        modelRows,
        hasModelData,
        protocolVersionRows,
        hasProtocolVersionData,
        dailyActivity,
        activityIncompleteTail,
        kpiIncompleteTail,
        toolDailySeries,
        toolRows,
        dateFilter,
        interval,
        queryFilters,
        canShowFeedback,
        feedbackContextKey,
        failedLoads,
        loadingSections,
    } = useValues(mcpDashboardOverviewLogic)
    const { setDateFilter, reloadAll, markFilterInteraction, openToolReport, loadSections } =
        useActions(mcpDashboardOverviewLogic)
    const { hiddenCards, isCardVisible } = useValues(mcpDashboardCardsLogic)
    const { showAllCards } = useActions(mcpDashboardCardsLogic)
    const { timezone } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const theme = useChartTheme()

    const showKpis = isCardVisible('kpis')
    const showActivity = isCardVisible('activity')
    const showToolUsage = isCardVisible('tool-usage')
    const showHarness = isCardVisible('harness')
    const showModel = isCardVisible('model') && hasModelData
    const showProtocolVersion = isCardVisible('protocol-version') && hasProtocolVersionData
    const showToolErrors = isCardVisible('tool-errors')
    const showToolLatency = isCardVisible('tool-latency')
    const showNotableSessions = isCardVisible('notable-sessions')
    const showRecentActivity = isCardVisible('recent-activity')
    const showUsage = showActivity || showToolUsage || showHarness || showModel || showProtocolVersion
    const showReliability = showToolErrors || showToolLatency || showNotableSessions
    const showsNoCards = !(showKpis || showUsage || showReliability || showRecentActivity)

    return (
        <div className="@container/mcp-overview flex min-w-0 flex-col gap-6">
            <McpSharedFilters
                pageKey="mcp-dashboard-overview"
                dataAttrPrefix="mcp-dashboard"
                onRefresh={reloadAll}
                refreshing={dashboardLoading}
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
                <DashboardCardsMenu
                    cardsWithoutData={[
                        ...(hasModelData ? [] : ['model' as const]),
                        ...(hasProtocolVersionData ? [] : ['protocol-version' as const]),
                    ]}
                />
            </McpSharedFilters>
            <MCPAnalyticsFeedbackPrompt
                contextKey={feedbackContextKey}
                eligible={canShowFeedback}
                prompt={MCP_ANALYTICS_DASHBOARD_FEEDBACK_PROMPT}
            />
            <MCPAnalyticsFirstLook />
            {showsNoCards &&
                (hiddenCards.length === MCP_DASHBOARD_CARDS.length ? (
                    <div className="flex flex-col items-start gap-2" data-attr="mcp-dashboard-all-cards-hidden">
                        <p className="mb-0">All cards are hidden.</p>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={showAllCards}
                            data-attr="mcp-dashboard-empty-show-all-cards"
                        >
                            Show all cards
                        </LemonButton>
                    </div>
                ) : (
                    <p className="mb-0" data-attr="mcp-dashboard-visible-cards-no-data">
                        The cards you kept have no data in this date range.
                    </p>
                ))}
            {showKpis && (
                <section className="flex min-w-0 flex-col gap-4" data-quill>
                    <h2 className="mb-4 text-xl font-semibold text-primary">Key metrics</h2>
                    <KpiTiles
                        kpis={headlineKpis}
                        users={periodTotals.users}
                        intentClusterCount={intentClusterCount}
                        kpisLoading={!!loadingSections.kpis}
                        usersLoading={!!loadingSections.periodTotals}
                        kpisFailed={failedLoads.kpis}
                        usersFailed={failedLoads.periodTotals}
                        onRetryKpis={() => loadSections([MCPDashboardSection.Kpis])}
                        onRetryUsers={() => loadSections([MCPDashboardSection.PeriodTotals])}
                        showIntentClusters={!!featureFlags[FEATURE_FLAGS.MCP_ANALYTICS_INTENT_ROUTING]}
                        theme={theme}
                        interval={interval}
                        incompleteTail={kpiIncompleteTail}
                    />
                </section>
            )}
            {showUsage && (
                <section className="flex min-w-0 flex-col gap-4" data-quill>
                    <h2 className="mb-4 text-xl font-semibold text-primary">Usage</h2>
                    <div className="flex min-w-0 flex-col gap-4">
                        <CardRow twoColumnsClassName="@min-[64rem]/mcp-overview:grid-cols-2">
                            {showActivity && (
                                <ActivityChart
                                    daily={dailyActivity}
                                    loading={!!loadingSections.activityRows}
                                    failed={failedLoads.activityRows}
                                    onRetry={() => loadSections([MCPDashboardSection.ActivityRows])}
                                    theme={theme}
                                    timezone={timezone}
                                    interval={interval}
                                    incompleteTail={activityIncompleteTail}
                                />
                            )}
                            {showToolUsage && (
                                <ToolUsageChart
                                    data={toolDailySeries}
                                    loading={!!loadingSections.toolDailyRows}
                                    failed={failedLoads.toolDailyRows}
                                    onRetry={() => loadSections([MCPDashboardSection.ToolDailyRows])}
                                    theme={theme}
                                    timezone={timezone}
                                    interval={interval}
                                />
                            )}
                        </CardRow>
                        <CardRow twoColumnsClassName="@min-[48rem]/mcp-overview:grid-cols-2">
                            {showHarness && (
                                <HarnessBarChart
                                    rows={harnessRows}
                                    loading={!!loadingSections.harnessRows}
                                    failed={failedLoads.harnessRows}
                                    onRetry={() => loadSections([MCPDashboardSection.HarnessRows])}
                                    theme={theme}
                                />
                            )}
                            {showModel && <ModelBarChart rows={modelRows} theme={theme} filters={queryFilters} />}
                        </CardRow>
                        {showProtocolVersion && <ProtocolVersionStrip rows={protocolVersionRows} theme={theme} />}
                    </div>
                </section>
            )}
            {showReliability && (
                <section className="flex min-w-0 flex-col gap-4" data-quill>
                    <h2 className="mb-0 text-xl font-semibold text-primary">Reliability</h2>
                    <CardRow twoColumnsClassName="@min-[64rem]/mcp-overview:grid-cols-2">
                        {showToolErrors && (
                            <ToolErrorRateChart
                                rows={rankToolsByErrorRate(toolRows)}
                                emptyMessage={rankedToolsEmptyMessage(toolRows)}
                                loading={!!loadingSections.toolRows}
                                failed={failedLoads.toolRows}
                                onRetry={() => loadSections([MCPDashboardSection.ToolRows])}
                                theme={theme}
                                onToolClick={openToolReport}
                            />
                        )}
                        {showToolLatency && (
                            <ToolLatencyChart
                                rows={rankToolsByP95(toolRows)}
                                emptyMessage={slowestToolsEmptyMessage(toolRows)}
                                loading={!!loadingSections.toolRows}
                                failed={failedLoads.toolRows}
                                onRetry={() => loadSections([MCPDashboardSection.ToolRows])}
                                theme={theme}
                                onToolClick={openToolReport}
                                action={
                                    // Negative margin keeps the header as tall as a title-only header.
                                    <LemonButton
                                        className="-my-1"
                                        type="secondary"
                                        size="xsmall"
                                        to={mcpToolQualityUrlWithDates(dateFilter, null, {
                                            column: 'p95_duration_ms',
                                            direction: 'DESC',
                                        })}
                                        data-attr="mcp-dashboard-slowest-tools-view-all"
                                    >
                                        View all tools
                                    </LemonButton>
                                }
                            />
                        )}
                    </CardRow>
                    {/* A block wrapper, because the card sets self-start for when it shares a grid row, and in
                        this flex column self-start would shrink it to its content width. */}
                    {showNotableSessions && (
                        <div className="min-w-0">
                            <NotableSessionsTable
                                sessions={notableSessions}
                                loading={!!loadingSections.sessionRows}
                                failed={failedLoads.sessionRows}
                                onRetry={() => loadSections([MCPDashboardSection.SessionRows])}
                            />
                        </div>
                    )}
                </section>
            )}
            {showRecentActivity && <RecentToolCallsCard filters={queryFilters} />}
        </div>
    )
}

// Pairs cards side by side, falling back to one column when a card in the pair is hidden.
function CardRow({
    twoColumnsClassName,
    children,
}: {
    twoColumnsClassName: string
    children: ReactNode
}): JSX.Element | null {
    const cards = Children.toArray(children)
    if (cards.length === 0) {
        return null
    }
    return <div className={cn('grid min-w-0 grid-cols-1 gap-4', cards.length > 1 && twoColumnsClassName)}>{cards}</div>
}
