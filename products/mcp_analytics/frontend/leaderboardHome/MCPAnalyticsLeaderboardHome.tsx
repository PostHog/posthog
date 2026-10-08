import { useActions, useValues } from 'kea'
import { type ReactNode, useCallback, useMemo } from 'react'

import { useChartTheme } from 'lib/charts/hooks'
import { formatPercentage } from 'lib/utils/numbers'
import { teamLogic } from 'scenes/teamLogic'

import { McpDateFilter } from '../components/McpDateFilter'
import { McpSharedFilters } from '../components/McpSharedFilters'
import { formatMsAsSeconds } from '../dashboard/formatters'
import { HarnessBarChart } from '../dashboard/HarnessBarChart'
import { ModelBarChart } from '../dashboard/ModelBarChart'
import { modelColor } from '../dashboard/modelColors'
import { mcpDashboardOverviewLogic } from '../mcpDashboardOverviewLogic'
import { FacetShareCard } from './FacetShareCard'
import { LabScoreboard } from './LabScoreboard'
import { mcpLeaderboardHomeLogic } from './mcpLeaderboardHomeLogic'
import { ShareOverTimeChart } from './ShareOverTimeChart'
import { TrendLineCard } from './TrendLineCard'

const formatErrorRateTick = (value: number): string => formatPercentage(value, { compact: true })

export function MCPAnalyticsLeaderboardHome(): JSX.Element {
    const {
        dateFilter,
        interval,
        queryFilters,
        dailyActivity,
        activityRowsLoading,
        harnessRows,
        harnessRowsLoading,
        modelRows,
        kpisLoading,
        usersLoading,
        sessionRowsLoading,
        modelRowsLoading,
        protocolVersionRowsLoading,
        toolDailyRowsLoading,
        toolRowsLoading,
    } = useValues(mcpDashboardOverviewLogic)
    const { setDateFilter, reloadAll, markFilterInteraction } = useActions(mcpDashboardOverviewLogic)
    const {
        facets,
        facetsLoading,
        latencyRowsLoading,
        leaderboardLoading,
        labShares,
        modelSeries,
        labSeries,
        protocolVersionSeries,
        latencySeries,
    } = useValues(mcpLeaderboardHomeLogic)
    const { timezone } = useValues(teamLogic)
    const theme = useChartTheme()

    const modelColorOf = useCallback((label: string) => modelColor(theme, label), [theme])
    const paletteColorOf = useCallback(
        (label: string, index: number) =>
            label === 'Other' ? theme.axisColor : theme.colors[index % theme.colors.length],
        [theme]
    )

    const errorRateLines = useMemo(
        () => [
            {
                key: 'error-rate',
                label: 'Error rate',
                data: dailyActivity.successes.map((successes, i) => {
                    const errors = dailyActivity.errors[i] ?? 0
                    const total = successes + errors
                    return total > 0 ? (errors / total) * 100 : 0
                }),
            },
        ],
        [dailyActivity]
    )
    const latencyLines = useMemo(
        () => [
            { key: 'p50', label: 'p50', data: latencySeries.p50 },
            { key: 'p95', label: 'p95', data: latencySeries.p95 },
        ],
        [latencySeries]
    )

    return (
        <div className="@container/mcp-overview flex min-w-0 flex-col gap-6" data-attr="mcp-leaderboard-home">
            <McpSharedFilters
                pageKey="mcp-dashboard-overview"
                dataAttrPrefix="mcp-dashboard"
                onRefresh={reloadAll}
                refreshing={
                    leaderboardLoading ||
                    kpisLoading ||
                    usersLoading ||
                    sessionRowsLoading ||
                    harnessRowsLoading ||
                    modelRowsLoading ||
                    protocolVersionRowsLoading ||
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

            <Section title="Models">
                <LabScoreboard shares={labShares} loading={facetsLoading} />
                <TwoColumns>
                    <ShareOverTimeChart
                        title="Share of calls by model"
                        labels={dailyActivity.labels}
                        series={modelSeries}
                        loading={facetsLoading}
                        theme={theme}
                        timezone={timezone}
                        interval={interval}
                        colorOf={modelColorOf}
                    />
                    <ModelBarChart rows={modelRows} theme={theme} filters={queryFilters} />
                </TwoColumns>
                <TwoColumns>
                    <ShareOverTimeChart
                        title="Share of calls by AI lab"
                        labels={dailyActivity.labels}
                        series={labSeries}
                        loading={facetsLoading}
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
                    title="Share of calls by MCP protocol version"
                    labels={dailyActivity.labels}
                    series={protocolVersionSeries}
                    loading={facetsLoading}
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
                        theme={theme}
                    />
                    <FacetShareCard
                        title="How we know the model"
                        rows={facets.modelSource}
                        loading={facetsLoading}
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
                        theme={theme}
                    />
                    <FacetShareCard
                        title="Most called tools"
                        rows={facets.tool}
                        loading={facetsLoading}
                        theme={theme}
                    />
                </TwoColumns>
                <FacetShareCard
                    title="Where intent comes from"
                    rows={facets.intentSource}
                    loading={facetsLoading}
                    theme={theme}
                />
            </Section>

            <Section title="Reliability">
                <TwoColumns>
                    <TrendLineCard
                        title="Error rate"
                        labels={dailyActivity.labels}
                        lines={errorRateLines}
                        loading={activityRowsLoading}
                        theme={theme}
                        timezone={timezone}
                        interval={interval}
                        formatTick={formatErrorRateTick}
                    />
                    <TrendLineCard
                        title="Latency"
                        labels={latencySeries.labels}
                        lines={latencyLines}
                        loading={latencyRowsLoading}
                        theme={theme}
                        timezone={timezone}
                        interval={interval}
                        formatTick={formatMsAsSeconds}
                    />
                </TwoColumns>
                <FacetShareCard title="Why calls fail" rows={facets.errorType} loading={facetsLoading} theme={theme} />
            </Section>
        </div>
    )
}

function Section({ title, children }: { title: string; children: ReactNode }): JSX.Element {
    return (
        <section className="flex min-w-0 flex-col gap-4" data-quill>
            <h2 className="mb-0 text-xl font-semibold text-primary">{title}</h2>
            {children}
        </section>
    )
}

function TwoColumns({ children }: { children: ReactNode }): JSX.Element {
    return <div className="grid min-w-0 grid-cols-1 gap-4 @min-[64rem]/mcp-overview:grid-cols-2">{children}</div>
}
