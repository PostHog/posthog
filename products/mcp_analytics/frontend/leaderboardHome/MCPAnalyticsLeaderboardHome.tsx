import { useActions, useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { useChartTheme } from 'lib/charts/hooks'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { formatPercentage } from 'lib/utils/numbers'
import { teamLogic } from 'scenes/teamLogic'

import { MCPDashboardSection } from '~/queries/schema/schema-general'

import { labColor, modelColors } from '../colors'
import { McpDateFilter } from '../components/McpDateFilter'
import { McpSharedFilters } from '../components/McpSharedFilters'
import { ActivityChart } from '../dashboard/ActivityChart'
import { Card } from '../dashboard/Card'
import { ChartSkeleton } from '../dashboard/ChartSkeleton'
import { formatMsAsSeconds } from '../dashboard/formatters'
import { HarnessBarChart } from '../dashboard/HarnessBarChart'
import { KpiTiles } from '../dashboard/KpiTiles'
import { ModelBarChart } from '../dashboard/ModelBarChart'
import { NotableSessionsTable } from '../dashboard/NotableSessionsTable'
import { ToolErrorRateChart } from '../dashboard/ToolErrorRateChart'
import { mcpDashboardOverviewLogic, rankedToolsEmptyMessage, rankToolsByErrorRate } from '../mcpDashboardOverviewLogic'
import { FacetShareCard } from './FacetShareCard'
import { LabScoreboard } from './LabScoreboard'
import { harnessErrorRateRows } from './leaderboardShares'
import { type FacetKey, mcpLeaderboardHomeLogic } from './mcpLeaderboardHomeLogic'
import { Section } from './Section'
import { ShareOverTimeChart } from './ShareOverTimeChart'
import { TrendLineCard } from './TrendLineCard'
import { TwoColumns } from './TwoColumns'

const formatErrorRateTick = (value: number): string => formatPercentage(value, { compact: true })

export function MCPAnalyticsLeaderboardHome(): JSX.Element {
    const {
        dashboardLoading,
        dateFilter,
        interval,
        queryFilters,
        dailyActivity,
        harnessRows,
        headlineKpis,
        periodTotals,
        intentClusterCount,
        kpiIncompleteTail,
        activityIncompleteTail,
        notableSessions,
        toolRows,
        failedLoads,
        loadingSections,
    } = useValues(mcpDashboardOverviewLogic)
    const { setDateFilter, reloadAll, markFilterInteraction, openToolReport, loadSections } =
        useActions(mcpDashboardOverviewLogic)
    const {
        facets,
        reliabilityRows,
        reliabilityFailed,
        scoreboardMetric,
        scoreboardShares,
        leaderboardModelRows,
        modelSeries,
        pageModels,
        modelRowLabelMap,
        labSeries,
        protocolVersionSeries,
        reliabilitySeries,
    } = useValues(mcpLeaderboardHomeLogic)
    const { setScoreboardMetric } = useActions(mcpLeaderboardHomeLogic)
    const { timezone } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const theme = useChartTheme()

    const failedFacet = (...keys: FacetKey[]): boolean => keys.some((key) => facets.failedFacets.includes(key))
    const loadingFacet = (...keys: FacetKey[]): boolean =>
        keys.some((key) => loadingSections[key as MCPDashboardSection])

    const pageModelColors = useMemo(() => modelColors(theme, pageModels), [theme, pageModels])
    const modelColorOf = useCallback((label: string) => pageModelColors.get(label), [pageModelColors])
    const labColorOf = useCallback((label: string) => labColor(theme, label), [theme])
    const paletteColorOf = useCallback(
        (label: string, index: number) =>
            label === 'Other' ? theme.axisColor : theme.colors[index % theme.colors.length],
        [theme]
    )

    const reliabilityUnavailable = reliabilityFailed || reliabilityRows.length === 0
    const harnessErrorRows = useMemo(() => harnessErrorRateRows(harnessRows), [harnessRows])
    const errorRateLines = useMemo(
        () => [
            { key: 'error-rate', label: 'Error rate', color: theme.colors[4], data: reliabilitySeries.errorRatePct },
        ],
        [reliabilitySeries, theme]
    )
    const latencyLines = useMemo(
        () => [
            { key: 'p50', label: 'p50', data: reliabilitySeries.p50 },
            { key: 'p95', label: 'p95', data: reliabilitySeries.p95 },
        ],
        [reliabilitySeries]
    )

    return (
        <div className="@container/mcp-overview flex min-w-0 flex-col gap-6" data-attr="mcp-leaderboard-home">
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
            </McpSharedFilters>

            <Section title="Key metrics">
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
            </Section>

            <Section title="Models">
                <LabScoreboard
                    shares={scoreboardShares}
                    loading={
                        scoreboardMetric === 'calls'
                            ? loadingFacet('model')
                            : loadingFacet('labUsers', 'namedModelUsers')
                    }
                    failed={
                        scoreboardMetric === 'calls' ? failedFacet('model') : failedFacet('labUsers', 'namedModelUsers')
                    }
                    metric={scoreboardMetric}
                    onMetricChange={setScoreboardMetric}
                />
                <TwoColumns>
                    <ShareOverTimeChart
                        title="Model share of calls over time"
                        labels={dailyActivity.labels}
                        series={modelSeries}
                        loading={loadingFacet('model')}
                        failed={failedFacet('model')}
                        theme={theme}
                        timezone={timezone}
                        interval={interval}
                        colorOf={modelColorOf}
                    />
                    {leaderboardModelRows.length === 0 && (loadingFacet('model') || loadingSections.modelRows) ? (
                        <Card title="Share of calls by model" className="min-w-0">
                            <div className="flex min-h-48 flex-col">
                                <ChartSkeleton kind="shares" />
                            </div>
                        </Card>
                    ) : (
                        <ModelBarChart
                            rows={leaderboardModelRows}
                            theme={theme}
                            filters={queryFilters}
                            colorOf={modelColorOf}
                            rowLabels={modelRowLabelMap}
                            fillHeight
                        />
                    )}
                </TwoColumns>
                <TwoColumns>
                    <ShareOverTimeChart
                        title="AI lab share of calls over time"
                        labels={dailyActivity.labels}
                        series={labSeries}
                        loading={loadingFacet('model')}
                        failed={failedFacet('model')}
                        theme={theme}
                        timezone={timezone}
                        interval={interval}
                        colorOf={labColorOf}
                    />
                    <HarnessBarChart
                        rows={harnessRows}
                        loading={!!loadingSections.harnessRows}
                        failed={failedLoads.harnessRows}
                        onRetry={() => loadSections([MCPDashboardSection.HarnessRows])}
                        theme={theme}
                        fillHeight
                    />
                </TwoColumns>
            </Section>

            <Section title="Protocol">
                <ShareOverTimeChart
                    title="Protocol version share of calls over time"
                    labels={dailyActivity.labels}
                    series={protocolVersionSeries}
                    loading={loadingFacet('protocolVersion')}
                    failed={failedFacet('protocolVersion')}
                    theme={theme}
                    timezone={timezone}
                    interval={interval}
                    colorOf={paletteColorOf}
                />
            </Section>

            <Section title="What agents do">
                <FacetShareCard
                    title="Most called tools"
                    rows={facets.tool}
                    loading={loadingFacet('tool')}
                    failed={failedFacet('tool')}
                    theme={theme}
                />
            </Section>

            <Section title="Reliability">
                <TwoColumns>
                    <TrendLineCard
                        title="Error rate"
                        labels={reliabilitySeries.labels}
                        lines={errorRateLines}
                        loading={!!loadingSections.reliability}
                        isEmpty={reliabilityUnavailable}
                        failed={reliabilityFailed}
                        theme={theme}
                        timezone={timezone}
                        interval={interval}
                        formatTick={formatErrorRateTick}
                    />
                    <TrendLineCard
                        title="Latency"
                        labels={reliabilitySeries.labels}
                        lines={latencyLines}
                        loading={!!loadingSections.reliability}
                        isEmpty={reliabilityUnavailable}
                        failed={reliabilityFailed}
                        theme={theme}
                        timezone={timezone}
                        interval={interval}
                        formatTick={formatMsAsSeconds}
                    />
                </TwoColumns>
                <TwoColumns>
                    <ToolErrorRateChart
                        rows={rankToolsByErrorRate(toolRows)}
                        emptyMessage={rankedToolsEmptyMessage(toolRows)}
                        loading={!!loadingSections.toolRows}
                        failed={failedLoads.toolRows}
                        onRetry={() => loadSections([MCPDashboardSection.ToolRows])}
                        theme={theme}
                        onToolClick={openToolReport}
                    />
                    <ToolErrorRateChart
                        rows={harnessErrorRows}
                        loading={!!loadingSections.harnessRows}
                        failed={failedLoads.harnessRows}
                        onRetry={() => loadSections([MCPDashboardSection.HarnessRows])}
                        theme={theme}
                        title="Error rate by harness"
                        emptyMessage="No harness data in this date range. Try a wider range."
                    />
                </TwoColumns>
                <TwoColumns>
                    <FacetShareCard
                        title="Why calls fail"
                        rows={facets.errorType}
                        loading={loadingFacet('errorType')}
                        failed={failedFacet('errorType')}
                        theme={theme}
                        maxVisibleRows={8}
                    />
                    <NotableSessionsTable
                        sessions={notableSessions}
                        loading={!!loadingSections.sessionRows}
                        failed={failedLoads.sessionRows}
                        onRetry={() => loadSections([MCPDashboardSection.SessionRows])}
                    />
                </TwoColumns>
            </Section>
        </div>
    )
}
