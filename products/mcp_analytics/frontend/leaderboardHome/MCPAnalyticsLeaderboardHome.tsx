import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo } from 'react'

import { useChartTheme } from 'lib/charts/hooks'
import { BrandMark } from 'lib/components/BrandMark/BrandMark'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { MCPDashboardSection } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { labMark, modelLab } from '../aiLabs'
import { InstrumentationEmptyState } from '../components/InstrumentationEmptyState'
import { McpDateFilter } from '../components/McpDateFilter'
import { McpSharedFilters } from '../components/McpSharedFilters'
import { HarnessLogo } from '../dashboard/harness'
import { UNIDENTIFIED_HARNESS_LABEL } from '../dashboard/harnessRegistry'
import { KpiTiles } from '../dashboard/KpiTiles'
import { ToolRankingCard } from '../dashboard/ToolRankingCard'
import { MCP_ANALYTICS_DASHBOARD_FEEDBACK_PROMPT } from '../feedback/constants'
import { MCPAnalyticsFeedbackPrompt } from '../feedback/MCPAnalyticsFeedbackPrompt'
import { MCPAnalyticsFirstLook } from '../firstLook/MCPAnalyticsFirstLook'
import { INSTRUMENTATION_FIXES } from '../instrumentationFixes'
import { activityUrlWithFilter } from '../mcpAnalyticsFiltersLogic'
import { mcpToolReportUrl } from '../mcpAnalyticsToolQualityLogic'
import {
    mcpDashboardOverviewLogic,
    rankedToolsEmptyMessage,
    rankToolsByErrorRate,
    rankToolsByP95,
    slowestToolsEmptyMessage,
} from '../mcpDashboardOverviewLogic'
import { ToolReportDrawer } from '../tool-quality/ToolReportDrawer'
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
    const { facets } = useValues(mcpLeaderboardHomeLogic)
    const { searchParams } = useValues(router)
    const { featureFlags } = useValues(featureFlagLogic)
    const { timezone } = useValues(teamLogic)
    const theme = useChartTheme()

    const failedFacet = (...keys: FacetKey[]): boolean => keys.some((key) => facets.failedFacets.includes(key))
    const loadingFacet = (...keys: FacetKey[]): boolean =>
        keys.some((key) => loadingSections[key as MCPDashboardSection])

    // The query returns the top tools of each ranking, so each table keeps its own top rows.
    const errorRanking = useMemo(() => rankToolsByErrorRate(toolRows).slice(0, 8), [toolRows])
    const latencyRanking = useMemo(() => rankToolsByP95(toolRows).slice(0, 8), [toolRows])
    // With a single version there is nothing to compare or migrate, so the card stays out of the way.
    const protocolVersionCount = new Set(facets.protocolVersion.map((row) => row.label).filter((v) => v !== 'Unknown'))
        .size
    const showProtocol = protocolVersionCount > 1 || (loadingFacet('protocolVersion') && protocolVersionCount === 0)
    const shareProps = { bucketKeys, theme, timezone, interval }
    const modelMissing = isMostlyLabeled(facets.model, ['Unknown'])
    const harnessMissing = isMostlyLabeled(facets.harness, [UNIDENTIFIED_HARNESS_LABEL, 'Unknown'])
    const usersAnonymous = isMostlyLabeled(facets.user, ['Unknown'])
    const openActivity = (change: Parameters<typeof activityUrlWithFilter>[1]): void =>
        router.actions.push(activityUrlWithFilter(searchParams, change))
    const eventFilter = (key: string, value: string): Parameters<typeof activityUrlWithFilter>[1] => ({
        property: { type: PropertyFilterType.Event, key, value: [value], operator: PropertyOperator.Exact },
    })

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

            <Section id="agent-feedback">
                <SuggestedFixesCard />
            </Section>

            <Section id="usage">
                <TwoColumns>
                    <ShareWidget
                        {...shareProps}
                        title="Share of calls by model"
                        rows={facets.model}
                        loading={loadingFacet('model')}
                        failed={failedFacet('model')}
                        iconOf={modelIcon}
                        onSelect={(model) => openActivity({ facets: { models: [model] } })}
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
                        onSelect={(harness) => openActivity({ facets: { harnesses: [harness] } })}
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
                            onSelect={(version) => openActivity(eventFilter('$mcp_protocol_version', version))}
                            dataAttr="mcp-dashboard-protocol-share"
                        />
                    ) : null}
                    <ShareWidget
                        {...shareProps}
                        title="Top people"
                        description="The people whose agents made the most calls. Each shows their email when they have one, otherwise their distinct ID."
                        rows={facets.user}
                        loading={loadingFacet('user')}
                        failed={failedFacet('user')}
                        onSelect={(user) =>
                            openActivity({
                                property: {
                                    type: PropertyFilterType.Person,
                                    key: user.includes('@') ? 'email' : 'distinct_id',
                                    value: [user],
                                    operator: PropertyOperator.Exact,
                                },
                            })
                        }
                        dataAttr="mcp-dashboard-user-share"
                        unknownLabel="Anonymous"
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
                        dataAttr="mcp-dashboard-tool-share"
                    />
                    <ShareWidget
                        {...shareProps}
                        title="Common errors"
                        rows={facets.errorType}
                        onSelect={(errorType) => openActivity({ facets: { errors: [errorType] } })}
                        loading={loadingFacet('errorType')}
                        failed={failedFacet('errorType')}
                        dataAttr="mcp-dashboard-error-type-share"
                    />
                </TwoColumns>
                <TwoColumns>
                    <ToolRankingCard
                        title="Tools with most errors"
                        rows={errorRanking}
                        metric="errorRate"
                        loading={!!loadingSections.toolRows}
                        failed={!!failedLoads.toolRows}
                        onRetry={() => loadSections([MCPDashboardSection.ToolRows])}
                        emptyMessage={rankedToolsEmptyMessage(toolRows)}
                        onSelect={openToolDrawer}
                        dataAttr="mcp-dashboard-most-errors-row"
                    />
                    <ToolRankingCard
                        title="Slowest tool calls"
                        rows={latencyRanking}
                        metric="p95"
                        loading={!!loadingSections.toolRows}
                        failed={!!failedLoads.toolRows}
                        onRetry={() => loadSections([MCPDashboardSection.ToolRows])}
                        emptyMessage={slowestToolsEmptyMessage(toolRows)}
                        onSelect={openToolDrawer}
                        dataAttr="mcp-dashboard-slowest-row"
                    />
                </TwoColumns>
            </Section>
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
