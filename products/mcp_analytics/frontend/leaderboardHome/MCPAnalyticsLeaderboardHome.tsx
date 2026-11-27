import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { useChartTheme } from 'lib/charts/hooks'
import { BrandMark } from 'lib/components/BrandMark/BrandMark'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { hogql } from 'lib/utils/hogql'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { HogQLQuery, MCPDashboardSection, NodeKind } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { labMark, modelLab } from '../aiLabs'
import { InstrumentationEmptyState } from '../components/InstrumentationEmptyState'
import { McpDateFilter } from '../components/McpDateFilter'
import { MCPDetailDrawer } from '../components/MCPDetailDrawer'
import { McpSharedFilters } from '../components/McpSharedFilters'
import { HarnessLogo } from '../dashboard/harness'
import { KpiTiles } from '../dashboard/KpiTiles'
import { type ErrorRanking, ToolErrorRateChart } from '../dashboard/ToolErrorRateChart'
import { ToolLatencyChart } from '../dashboard/ToolLatencyChart'
import { MCP_ANALYTICS_DASHBOARD_FEEDBACK_PROMPT } from '../feedback/constants'
import { MCPAnalyticsFeedbackPrompt } from '../feedback/MCPAnalyticsFeedbackPrompt'
import { MCPAnalyticsFirstLook } from '../firstLook/MCPAnalyticsFirstLook'
import { INSTRUMENTATION_FIXES } from '../instrumentationFixes'
import { mcpTabUrlWithFilter } from '../mcpAnalyticsFiltersLogic'
import { mcpToolQualityUrlWithDates, mcpToolReportUrl } from '../mcpAnalyticsToolQualityLogic'
import {
    mcpDashboardOverviewLogic,
    rankedToolsEmptyMessage,
    rankToolsByErrorRate,
    rankToolsByErrors,
    rankToolsByP95,
    slowestToolsEmptyMessage,
} from '../mcpDashboardOverviewLogic'
import { ToolReportDrawer } from '../tool-quality/ToolReportDrawer'
import { mcpUserUrl } from '../users/MCPAnalyticsUsers'
import { UserReport } from '../users/UserReport'
import { userReportLogic } from '../users/userReportLogic'
import { LabScoreboard } from './LabScoreboard'
import { isMostlyLabeled } from './leaderboardShares'
import { type FacetKey, mcpLeaderboardHomeLogic } from './mcpLeaderboardHomeLogic'
import { ProtocolVersionDescription } from './ProtocolVersionDescription'
import { Section } from './Section'
import { ShareWidget } from './ShareWidget'
import { SuggestedFixesCard } from './SuggestedFixesCard'
import { TwoColumns } from './TwoColumns'

// Matches CURRENT_PROTOCOL_VERSION in the protocol version breakdown query.
const CURRENT_PROTOCOL_VERSION = '2026-07-28'

const isCurrentProtocol = (version: string): boolean =>
    version === 'draft' || (/^\d{4}-\d{2}-\d{2}$/.test(version) && version >= CURRENT_PROTOCOL_VERSION)

const protocolLabel = (version: string): string => (isCurrentProtocol(version) ? `${version} (current)` : version)
const modelIcon = (model: string): JSX.Element => <BrandMark name={labMark(modelLab(model))} />
const harnessIcon = (harness: string): JSX.Element => <HarnessLogo category={harness} />

type FilterChange = Parameters<typeof mcpTabUrlWithFilter>[2]

export function MCPAnalyticsLeaderboardHome(): JSX.Element {
    const {
        dashboardLoading,
        dateFilter,
        interval,
        bucketKeys,
        headlineKpis,
        intentClusterCount,
        kpiIncompleteTail,
        toolRows,
        failedLoads,
        loadedSections,
        loadingSections,
        canShowFeedback,
        feedbackContextKey,
        drawerTool,
        drawerPosition,
        drawerPreviousTool,
        drawerNextTool,
        drawerTools,
    } = useValues(mcpDashboardOverviewLogic)
    const { setDateFilter, reloadAll, markFilterInteraction, loadSections, openToolDrawer, closeToolDrawer } =
        useActions(mcpDashboardOverviewLogic)
    const { facets, scoreboardMetric, scoreboardShares } = useValues(mcpLeaderboardHomeLogic)
    const { setScoreboardMetric } = useActions(mcpLeaderboardHomeLogic)
    const { searchParams } = useValues(router)
    const { featureFlags } = useValues(featureFlagLogic)
    const { timezone } = useValues(teamLogic)
    const theme = useChartTheme()
    const [openedUser, setOpenedUser] = useState<{ distinctId: string; label: string; labels: string[] } | null>(null)

    const failedFacet = (...keys: FacetKey[]): boolean => keys.some((key) => facets.failedFacets.includes(key))
    const loadingFacet = (...keys: FacetKey[]): boolean =>
        keys.some((key) => loadingSections[key as MCPDashboardSection])

    // The query returns the top tools of each ranking, so each chart keeps its own top rows.
    const [errorsBy, setErrorsBy] = useState<ErrorRanking>('rate')
    const errorRanking = useMemo(
        () => (errorsBy === 'rate' ? rankToolsByErrorRate(toolRows) : rankToolsByErrors(toolRows)).slice(0, 8),
        [toolRows, errorsBy]
    )
    const latencyRanking = useMemo(() => rankToolsByP95(toolRows).slice(0, 8), [toolRows])
    // With a single version there is nothing to compare or migrate, so the card stays out of the way.
    const protocolVersionCount = new Set(facets.protocolVersion.map((row) => row.label).filter((v) => v !== 'Unknown'))
        .size
    const showProtocol = protocolVersionCount > 1 || (loadingFacet('protocolVersion') && protocolVersionCount === 0)
    const shareProps = { bucketKeys, theme, timezone, interval }
    const modelMissing = isMostlyLabeled(facets.model, ['Unknown'])
    const harnessMissing = isMostlyLabeled(facets.harness, ['Unknown'])
    const usersAnonymous = isMostlyLabeled(facets.user, ['Unknown'])
    const openActivity = (change: FilterChange): void =>
        router.actions.push(mcpTabUrlWithFilter(urls.mcpAnalyticsActivity(), searchParams, change))
    // An error type is about which tools fail with it, so it opens Tool quality.
    const openToolQuality = (change: FilterChange): void =>
        router.actions.push(mcpTabUrlWithFilter(urls.mcpAnalyticsToolQuality(), searchParams, change))
    const eventFilter = (key: string, values: string[]): FilterChange => ({
        property: { type: PropertyFilterType.Event, key, value: values, operator: PropertyOperator.Exact },
    })
    // A chart's Unknown row counts the calls that didn't send the property.
    const notSetFilter = (key: string): FilterChange => ({
        property: { type: PropertyFilterType.Event, key, operator: PropertyOperator.IsNotSet },
    })
    // The label is the email, else the distinct ID, so an email label needs a lookup for the drawer.
    const openUser = async (label: string, labels: string[]): Promise<void> => {
        const match = label.includes('@')
            ? await api
                  .query<HogQLQuery>({
                      kind: NodeKind.HogQLQuery,
                      query: hogql`SELECT distinct_id FROM events
                          WHERE event = '$mcp_tool_call' AND {filters}
                              AND (distinct_id = ${label} OR toString(person.properties.email) = ${label})
                          ORDER BY timestamp DESC
                          LIMIT 1`,
                      filters: { dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo } },
                  })
                  .catch(() => null)
            : null
        setOpenedUser({ distinctId: String(match?.results?.[0]?.[0] ?? label), label, labels })
    }
    const userIndex = openedUser ? openedUser.labels.indexOf(openedUser.label) : -1
    const stepUser = (offset: number): (() => void) | null => {
        const next = openedUser?.labels[userIndex + offset]
        return openedUser && next ? () => void openUser(next, openedUser.labels) : null
    }

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
            <MCPAnalyticsFeedbackPrompt
                contextKey={feedbackContextKey}
                eligible={canShowFeedback}
                prompt={MCP_ANALYTICS_DASHBOARD_FEEDBACK_PROMPT}
            />
            <MCPAnalyticsFirstLook />

            <Section id="key-metrics">
                <KpiTiles
                    kpis={headlineKpis}
                    intentClusterCount={intentClusterCount}
                    kpisLoading={!!loadingSections.kpis}
                    usersLoading={!!loadingSections.periodTotals}
                    kpisLoaded={!!loadedSections.kpis}
                    usersLoaded={!!loadedSections.periodTotals}
                    kpisFailed={failedLoads.kpis}
                    usersFailed={failedLoads.periodTotals}
                    onRetryKpis={() => loadSections([MCPDashboardSection.Kpis])}
                    onRetryUsers={() => loadSections([MCPDashboardSection.PeriodTotals])}
                    showIntentClusters={!!featureFlags[FEATURE_FLAGS.MCP_ANALYTICS_INTENT_ROUTING]}
                    theme={theme}
                    interval={interval}
                    incompleteTail={kpiIncompleteTail}
                    usersAreSessions={usersAnonymous}
                />
            </Section>

            <Section id="models">
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
                    <ShareWidget
                        {...shareProps}
                        title="Share of calls by model"
                        rows={facets.model}
                        loading={loadingFacet('model')}
                        failed={failedFacet('model')}
                        iconOf={modelIcon}
                        onSelect={(model) => openActivity({ facets: { models: [model] } })}
                        onSelectOther={(models) => openActivity({ facets: { models } })}
                        onSelectUnknown={() => openActivity(notSetFilter('$mcp_llm_model'))}
                        dataAttr="mcp-dashboard-model-share"
                        setupEmptyState={
                            modelMissing ? (
                                <InstrumentationEmptyState
                                    fix={INSTRUMENTATION_FIXES.model}
                                    dataAttr="mcp-dashboard-model-share-setup"
                                />
                            ) : undefined
                        }
                    />
                    <ShareWidget
                        {...shareProps}
                        title="Share of calls by harness"
                        description="The app or agent that made the call, such as Claude Code or Cursor."
                        rows={facets.harness}
                        loading={loadingFacet('harness')}
                        failed={failedFacet('harness')}
                        iconOf={harnessIcon}
                        unknownLabel="Unidentified client"
                        onSelect={(harness) => openActivity({ facets: { harnesses: [harness] } })}
                        onSelectOther={(harnesses) => openActivity({ facets: { harnesses } })}
                        dataAttr="mcp-dashboard-harness-share"
                        setupEmptyState={
                            harnessMissing ? (
                                <InstrumentationEmptyState
                                    fix={INSTRUMENTATION_FIXES.harness}
                                    dataAttr="mcp-dashboard-harness-share-setup"
                                />
                            ) : undefined
                        }
                    />
                </TwoColumns>
            </Section>

            <Section id="agent-feedback">
                <SuggestedFixesCard />
            </Section>

            <Section id="usage">
                <TwoColumns>
                    {showProtocol ? (
                        <ShareWidget
                            {...shareProps}
                            title="Share of calls by protocol version"
                            description={<ProtocolVersionDescription />}
                            rows={facets.protocolVersion}
                            loading={loadingFacet('protocolVersion')}
                            failed={failedFacet('protocolVersion')}
                            labelOf={protocolLabel}
                            onSelect={(version) => openActivity(eventFilter('$mcp_protocol_version', [version]))}
                            onSelectOther={(versions) => openActivity(eventFilter('$mcp_protocol_version', versions))}
                            onSelectUnknown={() => openActivity(notSetFilter('$mcp_protocol_version'))}
                            dataAttr="mcp-dashboard-protocol-share"
                        />
                    ) : null}
                    <ShareWidget
                        {...shareProps}
                        title="Top users"
                        description="The people whose agents made the most calls. Each shows their email when they have one, otherwise their distinct ID."
                        rows={facets.user}
                        loading={loadingFacet('user')}
                        failed={failedFacet('user')}
                        onSelect={(label, labels) => void openUser(label, labels)}
                        dataAttr="mcp-dashboard-user-share"
                        unknownLabel="Anonymous"
                        sensitive
                        setupEmptyState={
                            usersAnonymous ? (
                                <InstrumentationEmptyState
                                    fix={INSTRUMENTATION_FIXES.identify}
                                    dataAttr="mcp-dashboard-user-share-setup"
                                />
                            ) : undefined
                        }
                    />
                </TwoColumns>
            </Section>

            <Section id="agents">
                <TwoColumns>
                    <ShareWidget
                        {...shareProps}
                        title="Most called tools"
                        rows={facets.tool}
                        loading={loadingFacet('tool')}
                        failed={failedFacet('tool')}
                        onSelect={openToolDrawer}
                        onSelectOther={(tools) => openActivity({ facets: { tools } })}
                        dataAttr="mcp-dashboard-tool-share"
                    />
                    <ShareWidget
                        {...shareProps}
                        title="Common errors"
                        rows={facets.errorType}
                        onSelect={(errorType) => openToolQuality({ facets: { errors: [errorType] } })}
                        onSelectOther={(errors) => openToolQuality({ facets: { errors } })}
                        loading={loadingFacet('errorType')}
                        failed={failedFacet('errorType')}
                        dataAttr="mcp-dashboard-error-type-share"
                    />
                </TwoColumns>
                <TwoColumns>
                    <ToolErrorRateChart
                        rows={errorRanking}
                        emptyMessage={
                            errorsBy === 'rate'
                                ? rankedToolsEmptyMessage(toolRows)
                                : toolRows.length > 0
                                  ? 'No tool calls failed in this date range.'
                                  : undefined
                        }
                        loading={!!loadingSections.toolRows}
                        failed={!!failedLoads.toolRows}
                        onRetry={() => loadSections([MCPDashboardSection.ToolRows])}
                        theme={theme}
                        onToolClick={(tool) =>
                            openToolDrawer(
                                tool,
                                errorRanking.map((row) => row.tool)
                            )
                        }
                        by={errorsBy}
                        onByChange={setErrorsBy}
                        dataAttr="mcp-dashboard-errors"
                        action={
                            <LemonButton
                                className="-my-1"
                                type="secondary"
                                size="xsmall"
                                to={mcpToolQualityUrlWithDates(dateFilter, null, {
                                    column: 'error_rate_pct',
                                    direction: 'DESC',
                                })}
                                data-attr="mcp-dashboard-error-rate-tools-view-all"
                            >
                                View all tools
                            </LemonButton>
                        }
                    />
                    <ToolLatencyChart
                        rows={latencyRanking}
                        emptyMessage={slowestToolsEmptyMessage(toolRows)}
                        loading={!!loadingSections.toolRows}
                        failed={!!failedLoads.toolRows}
                        onRetry={() => loadSections([MCPDashboardSection.ToolRows])}
                        theme={theme}
                        onToolClick={(tool) =>
                            openToolDrawer(
                                tool,
                                latencyRanking.map((row) => row.tool)
                            )
                        }
                        action={
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
                </TwoColumns>
            </Section>
            {openedUser ? (
                <MCPDetailDrawer
                    noun="user"
                    title={<span className="ph-no-capture">{openedUser.label}</span>}
                    position={userIndex >= 0 ? { index: userIndex, total: openedUser.labels.length } : null}
                    onPrevious={stepUser(-1)}
                    onNext={stepUser(1)}
                    fullPageHref={mcpUserUrl(openedUser.distinctId, dateFilter.dateFrom, dateFilter.dateTo)}
                    onClose={() => setOpenedUser(null)}
                    data-attr="mcp-dashboard-user-drawer"
                >
                    <BindLogic
                        logic={userReportLogic}
                        props={{
                            distinctId: openedUser.distinctId,
                            dateFrom: dateFilter.dateFrom,
                            dateTo: dateFilter.dateTo,
                        }}
                    >
                        <div data-quill>
                            <UserReport />
                        </div>
                    </BindLogic>
                </MCPDetailDrawer>
            ) : null}
            <ToolReportDrawer
                tool={drawerTool}
                position={drawerPosition}
                previousTool={drawerPreviousTool}
                nextTool={drawerNextTool}
                onOpen={(tool) => (tool ? openToolDrawer(tool, drawerTools) : closeToolDrawer())}
                fullPageHref={drawerTool ? mcpToolReportUrl(drawerTool, dateFilter) : ''}
                dataAttr="mcp-dashboard-tool-drawer"
            />
        </div>
    )
}
