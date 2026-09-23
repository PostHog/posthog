import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconCursor, IconPeople, IconRetention, IconTarget, IconTrends } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonCollapse, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { useLocalStorage } from 'lib/hooks/useLocalStorage'
import { suggestionsForSection } from 'scenes/marketing-analytics/Setup/sectionRouting'
import { SuggestionRow } from 'scenes/marketing-analytics/Setup/SuggestionRow'
import { teamLogic } from 'scenes/teamLogic'
import { MARKETING_ANALYTICS_DEFAULT_QUERY_TAGS } from 'scenes/web-analytics/common'
import { AttributionTab } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/AttributionTab'
import { AttributionTable } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/AttributionTable'
import { RetentionTab } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/RetentionTab/RetentionTab'
import {
    SetupSection,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { marketingAttributionLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAttributionLogic'
import { BREAKDOWN_LABELS } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingBreakdown'
import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { OverviewMetricCardGrid } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'
import { labelFromKey } from '~/queries/nodes/WebOverview/WebOverview'
import { Query } from '~/queries/Query/Query'
import {
    MarketingAnalyticsAttributionBreakdown,
    NodeKind,
    WebOverviewQuery,
    WebOverviewQueryResponse,
    WebStatsBreakdown,
} from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { CustomerAcquisitionCards } from './CustomerAcquisitionCards'
import { marketingAcquisitionLogic } from './marketingAcquisitionLogic'
import { marketingTrafficQueryContext } from './marketingTrafficQueryContext'
import { TRAFFIC_CHART_METRICS } from './trafficChartSeries'

const TRAFFIC_BREAKDOWNS = [
    { value: WebStatsBreakdown.InitialChannelType, label: 'Channel' },
    { value: WebStatsBreakdown.InitialUTMSource, label: 'UTM source' },
    { value: WebStatsBreakdown.InitialUTMCampaign, label: 'Campaign' },
    { value: WebStatsBreakdown.InitialUTMMedium, label: 'Medium' },
    { value: WebStatsBreakdown.InitialReferringDomain, label: 'Referring domain' },
    { value: WebStatsBreakdown.InitialPage, label: 'Landing page' },
]

const SECTIONS = [
    {
        key: 'acquisition',
        title: 'Acquisition',
        description: 'Visitors, sessions and pageviews',
        icon: <IconPeople />,
    },
    {
        key: 'engagement',
        title: 'Engagement',
        description: 'Session duration and bounce rate',
        icon: <IconCursor />,
    },
    {
        key: 'retention',
        title: 'Retention',
        description: 'Returning visitors by cohort',
        icon: <IconRetention />,
    },
    {
        key: 'conversion',
        title: 'Conversion',
        description: 'Goals and conversion paths',
        icon: <IconTarget />,
    },
    {
        key: 'revenue',
        title: 'Revenue',
        description: 'Revenue by attribution model',
        icon: <IconTrends />,
    },
]

// Scaffold for the redesigned marketing analytics dashboard, gated behind the
// `new-marketing-analytics-dashboard` feature flag.
export function NewMarketingAnalyticsDashboard(): JSX.Element {
    const [selectedSection, setSelectedSection] = useState('acquisition')
    const [trafficBreakdown, setTrafficBreakdown] = useState(WebStatsBreakdown.InitialChannelType)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const activeSection = SECTIONS.some(({ key }) => key === selectedSection) ? selectedSection : 'acquisition'
    const isTraffic = activeSection === 'acquisition' || activeSection === 'engagement'
    const { revenueGoals, selectedRevenueGoalId, revenueQuery, breakdownBy } = useValues(marketingAttributionLogic)
    const { setRevenueGoalId, setBreakdownBy } = useActions(marketingAttributionLogic)
    const {
        customerGoals,
        selectedCustomerGoal,
        customerConversionGoal,
        trafficOrderBy,
        trafficChartMetric,
        trafficChartSeries,
    } = useValues(marketingAcquisitionLogic)
    const { setCustomerGoalId, toggleTrafficSort, setTrafficChartMetric } = useActions(marketingAcquisitionLogic)
    const { dateFilter, compareFilter, shouldFilterTestAccounts } = useValues(marketingAnalyticsLogic)
    const { setDates, setCompareFilter, openSetup, reportDashboardSectionViewed, reportDashboardControlUsed } =
        useActions(marketingAnalyticsLogic)
    const { setupPlan, setupPlanLoading, visibleSuggestions } = useValues(setupPlanLogic)
    const { loadSetupPlan, reviewSuggestion } = useActions(setupPlanLogic)
    const [sourcesExpanded, setSourcesExpanded] = useLocalStorage('marketing-source-suggestions-expanded', false)
    const sourceSuggestions = visibleSuggestions.filter((suggestion) => suggestion.kind === 'connect_source')
    const reviewSources = (): void => openSetup(SetupSection.SOURCES, 'dashboard_source_suggestions')

    const [goalsExpanded, setGoalsExpanded] = useLocalStorage('marketing-goal-suggestions-expanded', false)
    const goalSuggestions = suggestionsForSection(visibleSuggestions, SetupSection.CONVERSION_GOALS)
    const reviewGoals = (): void => openSetup(SetupSection.CONVERSION_GOALS, 'dashboard_goal_suggestions')

    const requestedSetupPlan = useRef(false)
    useEffect(() => {
        if (!setupPlan && !setupPlanLoading && !requestedSetupPlan.current) {
            requestedSetupPlan.current = true
            loadSetupPlan()
        }
    }, [setupPlan, setupPlanLoading, loadSetupPlan])

    const reportedSection = useRef<string | null>(null)
    useEffect(() => {
        if (currentTeamLoading || reportedSection.current === activeSection) {
            return
        }
        reportedSection.current = activeSection
        reportDashboardSectionViewed(activeSection, {
            customerGoal: !!customerConversionGoal,
            revenueGoal: !!revenueQuery,
        })
    }, [activeSection, currentTeamLoading, customerConversionGoal, revenueQuery, reportDashboardSectionViewed])
    const reportControl = (control: string, value?: string | boolean): void =>
        reportDashboardControlUsed(activeSection, control, value)

    const dateRange = { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo }
    const query: WebOverviewQuery = {
        kind: NodeKind.WebOverviewQuery,
        dateRange,
        compareFilter,
        filterTestAccounts: shouldFilterTestAccounts,
        properties: [],
        tags: MARKETING_ANALYTICS_DEFAULT_QUERY_TAGS,
    }
    const overviewLogic = dataNodeLogic({ query, key: 'marketing-acquisition-overview' })
    const { response, responseLoading, responseError } = useValues(overviewLogic)
    const { loadData } = useActions(overviewLogic)
    const overview = response as WebOverviewQueryResponse | undefined
    const customerOverviewLogic = dataNodeLogic({
        query: { ...query, conversionGoal: activeSection === 'acquisition' ? customerConversionGoal : null },
        key: 'marketing-acquisition-customers',
        autoLoad: !!customerConversionGoal && activeSection === 'acquisition',
    })
    const {
        response: customerResponse,
        responseLoading: customersLoading,
        responseError: customersError,
    } = useValues(customerOverviewLogic)
    const { loadData: loadCustomers } = useActions(customerOverviewLogic)
    const customerOverview = customerResponse as WebOverviewQueryResponse | undefined
    const reviewCustomerGoals = (): void => openSetup(SetupSection.CONVERSION_GOALS, 'dashboard_customer_cards')

    return (
        <div className="mt-4 flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-2">
                <DateFilter dateFrom={dateFilter.dateFrom} dateTo={dateFilter.dateTo} onChange={setDates} />
                {isTraffic && (
                    <>
                        <CompareFilter compareFilter={compareFilter} updateCompareFilter={setCompareFilter} />
                        <LemonButton
                            size="small"
                            loading={
                                responseLoading ||
                                (activeSection === 'acquisition' && !!customerConversionGoal && customersLoading)
                            }
                            onClick={() => {
                                reportControl('reload_summary')
                                loadData('force_async')
                                if (activeSection === 'acquisition' && customerConversionGoal) {
                                    loadCustomers('force_async')
                                }
                            }}
                        >
                            Reload summary
                        </LemonButton>
                    </>
                )}
            </div>
            <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,24rem),1fr))] items-start gap-2 empty:hidden">
                {sourceSuggestions.length > 0 && (
                    <div className="border rounded relative">
                        <LemonButton className="absolute right-2 top-0 z-10" size="small" onClick={reviewSources}>
                            Review in Setup
                        </LemonButton>
                        <LemonCollapse
                            embedded
                            size="small"
                            activeKey={sourcesExpanded ? 'sources' : null}
                            onChange={(key) => {
                                reportControl('source_suggestions', key !== null)
                                setSourcesExpanded(key !== null)
                            }}
                            panels={[
                                {
                                    key: 'sources',
                                    header: {
                                        children: `Suggested ad sources (${sourceSuggestions.length})`,
                                        className: 'pr-36',
                                    },
                                    content: sourceSuggestions.map((suggestion) => (
                                        <SuggestionRow
                                            key={suggestion.id}
                                            suggestion={suggestion}
                                            currentSection={SetupSection.SOURCES}
                                            onReview={(item) => {
                                                reviewSources()
                                                reviewSuggestion(item)
                                            }}
                                        />
                                    )),
                                },
                            ]}
                        />
                    </div>
                )}
                {goalSuggestions.length > 0 && (
                    <div className="border rounded relative">
                        <LemonButton className="absolute right-2 top-0 z-10" size="small" onClick={reviewGoals}>
                            Review in Setup
                        </LemonButton>
                        <LemonCollapse
                            embedded
                            size="small"
                            activeKey={goalsExpanded ? 'goals' : null}
                            onChange={(key) => {
                                reportControl('goal_suggestions', key !== null)
                                setGoalsExpanded(key !== null)
                            }}
                            panels={[
                                {
                                    key: 'goals',
                                    header: {
                                        children: `Suggested conversion goals (${goalSuggestions.length})`,
                                        className: 'pr-36',
                                    },
                                    content: goalSuggestions.map((suggestion) => (
                                        <SuggestionRow
                                            key={suggestion.id}
                                            suggestion={suggestion}
                                            currentSection={SetupSection.CONVERSION_GOALS}
                                            onReview={(item) => {
                                                reviewGoals()
                                                reviewSuggestion(item)
                                            }}
                                        />
                                    )),
                                },
                            ]}
                        />
                    </div>
                )}
            </div>
            <nav aria-label="Dashboard sections" className="flex flex-wrap gap-1 rounded border p-1 w-fit max-w-full">
                {SECTIONS.map(({ key, title, icon }) => (
                    <LemonButton
                        key={key}
                        type="tertiary"
                        active={activeSection === key}
                        className={activeSection === key ? '!bg-accent-highlight !text-accent' : undefined}
                        icon={icon}
                        size="small"
                        data-attr={`marketing-dashboard-section-${key}`}
                        onClick={() => setSelectedSection(key)}
                        aria-pressed={activeSection === key}
                        aria-controls="marketing-dashboard-section"
                    >
                        {title}
                    </LemonButton>
                ))}
            </nav>
            <div id="marketing-dashboard-section" className="flex flex-col gap-4">
                {isTraffic &&
                    (responseError ? (
                        <LemonBanner
                            type="error"
                            action={{ children: 'Retry', onClick: () => loadData('force_async') }}
                        >
                            Could not load traffic metrics. Try again.
                        </LemonBanner>
                    ) : (
                        [
                            { key: 'acquisition', title: 'Acquisition', keys: ['visitors', 'sessions', 'views'] },
                            { key: 'engagement', title: 'Engagement', keys: ['session duration', 'bounce rate'] },
                        ]
                            .filter(({ key }) => key === activeSection)
                            .map(({ title, keys }) => (
                                <section key={title} className="flex flex-col gap-2" aria-label={title}>
                                    <h2 className="mb-0">{title}</h2>
                                    <p className="text-secondary mb-2">
                                        {SECTIONS.find(({ key }) => key === activeSection)?.description}
                                    </p>
                                    <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,12rem),1fr))] auto-rows-fr gap-2">
                                        <div className="contents">
                                            <OverviewMetricCardGrid
                                                layout="contents"
                                                items={keys.flatMap((key) =>
                                                    (overview?.results?.filter((item) => item.key === key) ?? []).map(
                                                        (item) => ({
                                                            ...item,
                                                            value: item.value,
                                                        })
                                                    )
                                                )}
                                                loading={responseLoading}
                                                numSkeletons={keys.length}
                                                samplingRate={overview?.samplingRate}
                                                preComputeStrategy={overview?.preComputeStrategy}
                                                labelFromKey={labelFromKey}
                                            />
                                        </div>
                                        {activeSection === 'acquisition' && (
                                            <CustomerAcquisitionCards
                                                configurationLoading={currentTeamLoading}
                                                configured={!!customerConversionGoal}
                                                loading={customersLoading || responseLoading}
                                                error={!!customersError}
                                                customerResults={customerOverview?.results}
                                                trafficResults={overview?.results}
                                                samplingRate={customerOverview?.samplingRate}
                                                onConfigure={reviewCustomerGoals}
                                                onRetry={() => loadCustomers('force_async')}
                                            />
                                        )}
                                    </div>
                                    {activeSection === 'acquisition' && customerConversionGoal && (
                                        <div className="flex flex-wrap items-center gap-2">
                                            <span>New customer goal</span>
                                            <LemonSelect
                                                aria-label="Customer goal"
                                                value={selectedCustomerGoal?.conversion_goal_id}
                                                onChange={(value) => {
                                                    reportControl('customer_goal')
                                                    setCustomerGoalId(value)
                                                }}
                                                options={customerGoals.map((goal) => ({
                                                    value: goal.conversion_goal_id,
                                                    label: goal.conversion_goal_name,
                                                }))}
                                            />
                                            <span className="text-secondary text-xs">
                                                Unique visitors completing this goal in the period. Use a
                                                once-per-customer goal to measure new customers.
                                            </span>
                                        </div>
                                    )}
                                </section>
                            ))
                    ))}
                {activeSection === 'conversion' && (
                    <section aria-label="Conversion" className="flex flex-col gap-2">
                        <h2 className="mb-0">Conversion</h2>
                        <p className="text-secondary mb-2">
                            {SECTIONS.find(({ key }) => key === activeSection)?.description}
                        </p>
                        <AttributionTab />
                    </section>
                )}
                {activeSection === 'retention' && (
                    <section aria-label="Retention" className="flex flex-col gap-2">
                        <h2 className="mb-0">Retention</h2>
                        <p className="text-secondary mb-0">
                            Follow visitors acquired in the selected date range across subsequent periods.
                        </p>
                        <RetentionTab />
                    </section>
                )}
                {activeSection === 'revenue' && (
                    <section aria-label="Revenue" className="flex flex-col gap-4">
                        <h2 className="mb-0">Revenue</h2>
                        {currentTeamLoading || !currentTeam ? (
                            <LemonSkeleton className="h-40" />
                        ) : revenueQuery ? (
                            <>
                                <div className="flex flex-wrap items-center gap-2">
                                    <DateFilter
                                        dateFrom={dateFilter.dateFrom}
                                        dateTo={dateFilter.dateTo}
                                        onChange={setDates}
                                    />
                                    <LemonSelect
                                        value={selectedRevenueGoalId}
                                        onChange={(value) => {
                                            if (value) {
                                                reportControl('revenue_goal')
                                                setRevenueGoalId(value)
                                            }
                                        }}
                                        options={revenueGoals.map((goal) => ({
                                            value: goal.conversion_goal_id,
                                            label: goal.conversion_goal_name,
                                        }))}
                                        data-attr="marketing-revenue-goal"
                                    />
                                    <LemonSelect
                                        value={breakdownBy}
                                        onChange={(value) => {
                                            reportControl('revenue_breakdown', value)
                                            setBreakdownBy(value)
                                        }}
                                        options={Object.values(MarketingAnalyticsAttributionBreakdown).map((value) => ({
                                            value,
                                            label: BREAKDOWN_LABELS[value],
                                        }))}
                                        data-attr="marketing-revenue-breakdown"
                                    />
                                </div>
                                <p className="text-secondary mb-0">
                                    Compare attributed value across models for one revenue goal at a time.
                                </p>
                                <AttributionTable
                                    metric="revenue"
                                    query={revenueQuery}
                                    attachTo={marketingAnalyticsLogic}
                                />
                            </>
                        ) : (
                            <LemonBanner
                                type="info"
                                action={{
                                    children: 'Review in Setup',
                                    onClick: () => openSetup(SetupSection.CONVERSION_GOALS, 'dashboard_revenue_banner'),
                                }}
                            >
                                Choose an event or action goal that sums an amount and mark it as Revenue in Setup.
                            </LemonBanner>
                        )}
                    </section>
                )}
                {isTraffic && (
                    <>
                        {activeSection === 'acquisition' && (
                            <LemonCard hoverEffect={false}>
                                <div className="flex flex-wrap justify-between items-center gap-2">
                                    <h3 className="mb-0">
                                        {`${TRAFFIC_CHART_METRICS.find(({ value }) => value === trafficChartMetric)?.label} over time`}
                                    </h3>
                                    <LemonSelect
                                        size="small"
                                        value={trafficChartMetric}
                                        onChange={(value) => {
                                            if (value) {
                                                reportControl('chart_metric', value)
                                                setTrafficChartMetric(value)
                                            }
                                        }}
                                        options={TRAFFIC_CHART_METRICS.map(({ value, label }) => ({
                                            value,
                                            label,
                                            disabledReason:
                                                value === 'new_customers' && !customerConversionGoal
                                                    ? 'Mark a conversion goal as a new customer goal in Setup first.'
                                                    : undefined,
                                        }))}
                                        aria-label="Chart metric"
                                        data-attr="marketing-traffic-chart-metric"
                                    />
                                </div>
                                <p className="text-secondary text-sm">All traffic in the selected period.</p>
                                <div className="flex flex-col h-80">
                                    <Query
                                        key={`${activeSection}-${trafficChartMetric}`}
                                        query={{
                                            kind: NodeKind.InsightVizNode,
                                            source: {
                                                kind: NodeKind.TrendsQuery,
                                                dateRange,
                                                compareFilter,
                                                filterTestAccounts: shouldFilterTestAccounts,
                                                interval: 'day',
                                                tags: MARKETING_ANALYTICS_DEFAULT_QUERY_TAGS,
                                                series: [trafficChartSeries],
                                                trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
                                            },
                                            embedded: true,
                                            showTable: false,
                                            hidePersonsModal: true,
                                        }}
                                        readOnly
                                    />
                                </div>
                            </LemonCard>
                        )}
                        <LemonCard hoverEffect={false}>
                            <div className="flex flex-wrap justify-between items-center gap-2 mb-3">
                                <h3 className="mb-0">
                                    {`${activeSection === 'acquisition' ? 'Acquisition' : 'Engagement'} by ${TRAFFIC_BREAKDOWNS.find(({ value }) => value === trafficBreakdown)?.label.toLowerCase()}`}
                                </h3>
                                <div className="flex items-center gap-2">
                                    <span>Breakdown by</span>
                                    <LemonSelect
                                        value={trafficBreakdown}
                                        onChange={(value) => {
                                            reportControl('traffic_breakdown', value)
                                            setTrafficBreakdown(value)
                                        }}
                                        options={TRAFFIC_BREAKDOWNS}
                                        aria-label="Traffic breakdown"
                                    />
                                </div>
                            </div>
                            <p className="text-secondary text-sm">
                                Grouped by session entry. UTM source and referring domain are separate breakdowns.
                                Visitors can appear in more than one row.
                            </p>
                            <Query
                                query={{
                                    kind: NodeKind.DataTableNode,
                                    source: {
                                        kind: NodeKind.WebStatsTableQuery,
                                        breakdownBy: trafficBreakdown,
                                        orderBy: trafficOrderBy[activeSection],
                                        dateRange,
                                        compareFilter,
                                        filterTestAccounts: shouldFilterTestAccounts,
                                        includeBounceRate: activeSection === 'engagement',
                                        includeTrafficMetrics: activeSection === 'acquisition',
                                        conversionGoal: activeSection === 'acquisition' ? customerConversionGoal : null,
                                        properties: [],
                                        limit: 25,
                                        tags: MARKETING_ANALYTICS_DEFAULT_QUERY_TAGS,
                                    },
                                    hiddenColumns:
                                        activeSection === 'engagement'
                                            ? ['context.columns.views']
                                            : [
                                                  'context.columns.total_conversions',
                                                  ...(customerConversionGoal ? ['context.columns.cross_sell'] : []),
                                              ],
                                    full: true,
                                    embedded: false,
                                    showOpenEditorButton: false,
                                }}
                                context={{
                                    ...marketingTrafficQueryContext(trafficOrderBy[activeSection], (field) =>
                                        toggleTrafficSort(activeSection, field)
                                    ),
                                    compareFilter,
                                }}
                                readOnly
                            />
                        </LemonCard>
                    </>
                )}
            </div>
        </div>
    )
}
