import { useActions, useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { Skeleton } from '@posthog/quill-primitives'

import { useChartTheme } from 'lib/charts/hooks'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { formatPercentage } from 'lib/utils/numbers'
import { teamLogic } from 'scenes/teamLogic'

import { McpDateFilter } from '../components/McpDateFilter'
import { McpSharedFilters } from '../components/McpSharedFilters'
import { ActivityChart } from '../dashboard/ActivityChart'
import { Card } from '../dashboard/Card'
import { formatMsAsSeconds } from '../dashboard/formatters'
import { HarnessBarChart } from '../dashboard/HarnessBarChart'
import { KpiTiles } from '../dashboard/KpiTiles'
import { ModelBarChart } from '../dashboard/ModelBarChart'
import { modelColor } from '../dashboard/modelColors'
import { NotableSessionsTable } from '../dashboard/NotableSessionsTable'
import { ToolErrorRateChart } from '../dashboard/ToolErrorRateChart'
import { mcpDashboardOverviewLogic } from '../mcpDashboardOverviewLogic'
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
        activityRowsLoading,
        harnessRows,
        harnessRowsLoading,
        modelRows,
        kpis,
        kpisLoading,
        users,
        usersLoading,
        intentClusterCount,
        kpiIncompleteTail,
        activityIncompleteTail,
        notableSessions,
        toolRows,
        sessionRowsLoading,
        modelRowsLoading,
        toolRowsLoading,
    } = useValues(mcpDashboardOverviewLogic)
    const { setDateFilter, reloadAll, markFilterInteraction, openToolReport } = useActions(mcpDashboardOverviewLogic)
    const {
        facets,
        facetsLoading,
        reliabilityRows,
        reliabilityRowsLoading,
        reliabilityFailed,
        leaderboardLoading,
        scoreboardMetric,
        scoreboardShares,
        modelSeries,
        labSeries,
        protocolVersionSeries,
        reliabilitySeries,
    } = useValues(mcpLeaderboardHomeLogic)
    const { setScoreboardMetric } = useActions(mcpLeaderboardHomeLogic)
    const { timezone } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const theme = useChartTheme()

    const failedFacet = (...keys: FacetKey[]): boolean => keys.some((key) => facets.failedFacets.includes(key))

    const modelColorOf = useCallback((label: string) => modelColor(theme, label), [theme])
    const paletteColorOf = useCallback(
        (label: string, index: number) =>
            label === 'Other' ? theme.axisColor : theme.colors[index % theme.colors.length],
        [theme]
    )

    const harnessErrorRows = useMemo(() => harnessErrorRateRows(harnessRows), [harnessRows])
    const errorRateLines = useMemo(
        () => [{ key: 'error-rate', label: 'Error rate', data: reliabilitySeries.errorRatePct }],
        [reliabilitySeries]
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
                refreshing={dashboardLoading || leaderboardLoading}
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
                <ActivityChart
                    daily={dailyActivity}
                    loading={activityRowsLoading}
                    theme={theme}
                    timezone={timezone}
                    interval={interval}
                    incompleteTail={activityIncompleteTail}
                />
            </Section>

            <Section title="Models">
                <LabScoreboard
                    shares={scoreboardShares}
                    loading={facetsLoading}
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
                        loading={facetsLoading}
                        failed={failedFacet('model')}
                        theme={theme}
                        timezone={timezone}
                        interval={interval}
                        colorOf={modelColorOf}
                    />
                    {modelRowsLoading && modelRows.length === 0 ? (
                        <Card title="Share of calls by model" className="min-w-0">
                            <Skeleton className="h-48 w-full" />
                        </Card>
                    ) : (
                        <ModelBarChart rows={modelRows} theme={theme} filters={queryFilters} />
                    )}
                </TwoColumns>
                <TwoColumns>
                    <ShareOverTimeChart
                        title="AI lab share of calls over time"
                        labels={dailyActivity.labels}
                        series={labSeries}
                        loading={facetsLoading}
                        failed={failedFacet('model')}
                        theme={theme}
                        timezone={timezone}
                        interval={interval}
                        colorOf={paletteColorOf}
                    />
                    <HarnessBarChart rows={harnessRows} loading={harnessRowsLoading} theme={theme} />
                </TwoColumns>
            </Section>

            <Section title="Protocol and sign-in">
                <ShareOverTimeChart
                    title="Protocol version share of calls over time"
                    labels={dailyActivity.labels}
                    series={protocolVersionSeries}
                    loading={facetsLoading}
                    failed={failedFacet('protocolVersion')}
                    theme={theme}
                    timezone={timezone}
                    interval={interval}
                    colorOf={paletteColorOf}
                />
                <TwoColumns>
                    <FacetShareCard
                        title="How agents sign in"
                        rows={facets.authMethod}
                        loading={facetsLoading}
                        failed={failedFacet('authMethod')}
                        theme={theme}
                    />
                    <FacetShareCard
                        title="How we know the model"
                        rows={facets.modelSource}
                        loading={facetsLoading}
                        failed={failedFacet('modelSource')}
                        theme={theme}
                    />
                </TwoColumns>
            </Section>

            <Section title="What agents do">
                <TwoColumns>
                    <FacetShareCard
                        title="Tool categories"
                        rows={facets.toolCategory}
                        loading={facetsLoading}
                        failed={failedFacet('toolCategory')}
                        theme={theme}
                    />
                    <FacetShareCard
                        title="Most called tools"
                        rows={facets.tool}
                        loading={facetsLoading}
                        failed={failedFacet('tool')}
                        theme={theme}
                    />
                </TwoColumns>
                <FacetShareCard
                    title="Where intent comes from"
                    rows={facets.intentSource}
                    loading={facetsLoading}
                    failed={failedFacet('intentSource')}
                    theme={theme}
                />
            </Section>

            <Section title="Reliability">
                <TwoColumns>
                    <TrendLineCard
                        title="Error rate"
                        labels={reliabilitySeries.labels}
                        lines={errorRateLines}
                        loading={reliabilityRowsLoading}
                        isEmpty={reliabilityRows.length === 0}
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
                        loading={reliabilityRowsLoading}
                        isEmpty={reliabilityRows.length === 0}
                        failed={reliabilityFailed}
                        theme={theme}
                        timezone={timezone}
                        interval={interval}
                        formatTick={formatMsAsSeconds}
                    />
                </TwoColumns>
                <TwoColumns>
                    <FacetShareCard
                        title="Why calls fail"
                        rows={facets.errorType}
                        loading={facetsLoading}
                        failed={failedFacet('errorType')}
                        theme={theme}
                    />
                    <ToolErrorRateChart
                        rows={harnessErrorRows}
                        loading={harnessRowsLoading}
                        theme={theme}
                        title="Error rate by harness"
                        emptyMessage="No harness data yet."
                    />
                </TwoColumns>
                <TwoColumns>
                    <ToolErrorRateChart
                        rows={toolRows}
                        loading={toolRowsLoading}
                        theme={theme}
                        onToolClick={openToolReport}
                    />
                    <NotableSessionsTable sessions={notableSessions} loading={sessionRowsLoading} />
                </TwoColumns>
            </Section>
        </div>
    )
}
