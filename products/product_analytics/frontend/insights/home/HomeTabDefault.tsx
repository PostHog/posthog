import { useActions, useMountedLogic, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconCalendar } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Link } from 'lib/lemon-ui/Link'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { cn } from 'lib/utils/css-classes'
import { CUSTOM_OPTION_KEY, dateMapping } from 'lib/utils/dateFilters'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'

import { HomeTabChartCard } from './HomeTabChartCard'
import { homeTabDefaultLogic, type HomeTabViewKey } from './homeTabDefaultLogic'
import {
    getHomeTabAudienceOptions,
    getHomeTabBreakdownOptions,
    getHomeTabChartOptions,
    getHomeTabStatQueries,
} from './homeTabDefaultTiles'
import { HomeTabExplore } from './HomeTabExplore'
import { homeTabLoadTimeLogic } from './homeTabLoadTimeLogic'
import { homeTabChartInsightId, homeTabStatKey, homeTabStatTrendKey } from './homeTabQueryKeys'
import { HomeTabReloadButton } from './HomeTabReloadButton'
import { HomeTabStatTiles } from './HomeTabStatTiles'
import { HomeTabView } from './HomeTabView'
import { getHomeTabViewLayout } from './homeTabViewCharts'

const HOME_DATE_OPTIONS = dateMapping.filter((option) => option.key !== CUSTOM_OPTION_KEY)

const HOME_VIEW_TABS: { key: HomeTabViewKey; label: string }[] = [
    { key: 'overview', label: 'Overview' },
    { key: 'new_users', label: 'New users' },
    { key: 'engagement', label: 'Engagement' },
    { key: 'retention', label: 'Retention' },
]

const VIEWS_WITH_COMPARE: HomeTabViewKey[] = ['overview', 'new_users', 'engagement']

export function HomeTabDefault({ dashboardActions }: { dashboardActions?: ReactNode }): JSX.Element {
    useAttachedLogic(homeTabDefaultLogic(), savedInsightsLogic)
    const { dateRange, compare, selectedMetric, selectedContentKey, selectedView, showViews } =
        useValues(homeTabDefaultLogic)
    const { setDates, setCompare, setSelectedMetric, setSelectedContentKey, setSelectedView } =
        useActions(homeTabDefaultLogic)
    const { currentTeamId } = useValues(teamLogic)
    const showCompare = !showViews || VIEWS_WITH_COMPARE.includes(selectedView)

    const metricCharts = getHomeTabChartOptions(dateRange, compare)
    const audienceCharts = getHomeTabAudienceOptions(dateRange)
    const breakdownCharts = getHomeTabBreakdownOptions(dateRange)
    const primaryChart = metricCharts.find((option) => option.key === selectedMetric) ?? metricCharts[0]
    const retentionChart =
        metricCharts.find((option) => option.key === 'retention') ?? metricCharts[metricCharts.length - 1]
    const contentChart = breakdownCharts.find((option) => option.key === selectedContentKey) ?? breakdownCharts[0]
    const eventsChart =
        breakdownCharts.find((option) => option.key === 'top_events') ?? breakdownCharts[breakdownCharts.length - 1]

    useMountedLogic(
        homeTabLoadTimeLogic({
            teamId: currentTeamId,
            tileIds: [
                ...new Set(
                    getHomeTabStatQueries(dateRange, compare).flatMap((stat) => [
                        homeTabStatKey(currentTeamId, stat.key),
                        homeTabStatTrendKey(currentTeamId, stat),
                    ])
                ),
                ...[primaryChart, contentChart, eventsChart, ...audienceCharts, retentionChart].map((chart) =>
                    insightVizDataNodeKey({ dashboardItemId: homeTabChartInsightId(currentTeamId, chart.key) })
                ),
            ],
            defaultDateRange: dateRange.date_from === '-7d' && !dateRange.date_to,
            compare,
        })
    )

    return (
        <div className="@container/home-overview flex flex-col gap-4 @max-[32rem]/saved-insights:gap-3">
            {showViews && (
                <LemonTabs
                    activeKey={selectedView}
                    onChange={setSelectedView}
                    tabs={HOME_VIEW_TABS}
                    className="[&>ul]:mb-0"
                    data-attr="home-tab-views"
                />
            )}

            <div
                className={cn(
                    'flex flex-wrap items-center justify-between gap-2',
                    !showViews && 'border-b border-primary pb-2 @min-[32rem]/home-overview:pb-3'
                )}
            >
                <div className="flex w-full items-center justify-between gap-2 @min-[48rem]/home-overview:w-auto">
                    {!showViews && (
                        <h2 className="m-0 min-w-0 text-lg font-semibold">
                            <span className="hidden @min-[32rem]/home-overview:inline">Product Analytics </span>
                            <span>Overview</span>
                        </h2>
                    )}
                    <div className="shrink-0 whitespace-nowrap @min-[48rem]/saved-insights:hidden">
                        {dashboardActions}
                    </div>
                </div>
                <div
                    className={cn(
                        'home-tab-date-controls grid w-full min-w-0 gap-2 [&_.LemonButton]:h-full [&_.LemonButton__content]:truncate @max-[32rem]/home-overview:[&_.LemonButton__content]:text-xs @min-[48rem]/home-overview:flex @min-[48rem]/home-overview:w-auto @min-[48rem]/home-overview:flex-wrap',
                        showCompare ? 'grid-cols-[1fr_1fr_auto]' : 'grid-cols-[1fr_auto]'
                    )}
                >
                    <div className="min-w-0 [&_.LemonButton]:w-full @min-[48rem]/home-overview:[&_.LemonButton]:w-auto">
                        <DateFilter
                            showCustom
                            showExplicitDateToggle
                            dateFrom={dateRange.date_from}
                            dateTo={dateRange.date_to}
                            explicitDate={dateRange.explicitDate ?? false}
                            dateOptions={HOME_DATE_OPTIONS}
                            onChange={setDates}
                            makeLabel={(label) => (
                                <span className="flex items-center gap-1.5">
                                    <IconCalendar />
                                    <span>{label}</span>
                                </span>
                            )}
                        />
                    </div>
                    {showCompare && (
                        <div className="min-w-0 [&_.LemonSelect]:w-full [&_.LemonButton]:w-full @min-[48rem]/home-overview:[&_.LemonSelect]:w-auto @min-[48rem]/home-overview:[&_.LemonButton]:w-auto">
                            <CompareFilter
                                compareFilter={{ compare }}
                                updateCompareFilter={(filter) => setCompare(!!filter.compare)}
                                allowCustomComparison={false}
                            />
                        </div>
                    )}
                    <HomeTabReloadButton />
                </div>
            </div>

            {showViews && selectedView !== 'overview' ? (
                <HomeTabView
                    key={selectedView}
                    view={selectedView}
                    layout={getHomeTabViewLayout(selectedView, dateRange, compare)}
                    label={HOME_VIEW_TABS.find(({ key }) => key === selectedView)?.label ?? ''}
                    note={
                        selectedView === 'new_users' ? (
                            <>
                                Landing pages and referrers for new visitors are in{' '}
                                <Link to={urls.webAnalytics()} data-attr="home-tab-new-users-web-analytics">
                                    Web analytics
                                </Link>
                                .
                            </>
                        ) : undefined
                    }
                />
            ) : (
                <>
                    <HomeTabStatTiles
                        stats={getHomeTabStatQueries(dateRange, compare)}
                        compare={compare}
                        selectedKey={selectedMetric}
                        onSelect={setSelectedMetric}
                        label="Overview metrics"
                    />

                    <HomeTabChartCard
                        key={primaryChart.key}
                        option={primaryChart}
                        size="primary"
                        source="Pageviews and screen views"
                        loadPriority={0}
                    />

                    <section className="flex flex-col gap-3" aria-label="What people do">
                        <div className="flex flex-wrap items-baseline justify-between gap-2">
                            <h2 className="m-0 text-base font-semibold">What people do</h2>
                            <span className="text-xs text-secondary">
                                Most common content and events in this period
                            </span>
                        </div>
                        <div className="grid min-w-0 grid-cols-1 gap-3 @min-[44rem]/home-overview:grid-cols-2">
                            <HomeTabChartCard
                                key={contentChart.key}
                                option={contentChart}
                                size="ranking"
                                loadPriority={2}
                                source={selectedContentKey === 'top_pages' ? 'Pageviews' : 'Screen views'}
                                control={
                                    <LemonSelect
                                        size="small"
                                        value={selectedContentKey}
                                        onChange={(value) => value && setSelectedContentKey(value)}
                                        options={[
                                            { value: 'top_pages', label: 'Pages' },
                                            { value: 'top_screens', label: 'Screens' },
                                        ]}
                                        dropdownMatchSelectWidth={false}
                                        data-attr="home-tab-content-chart"
                                    />
                                }
                            />
                            <HomeTabChartCard
                                option={eventsChart}
                                size="ranking"
                                source="Captured events"
                                loadPriority={2}
                            />
                        </div>
                    </section>

                    <section className="flex flex-col gap-3" aria-label="Your audience">
                        <h2 className="m-0 text-base font-semibold">Your audience</h2>
                        <div className="grid min-w-0 grid-cols-1 gap-3 @min-[56rem]/home-overview:grid-cols-[2fr_1fr]">
                            {audienceCharts.map((option) => (
                                <HomeTabChartCard
                                    key={option.key}
                                    option={option}
                                    size="supporting"
                                    source="Pageviews and screen views"
                                    loadPriority={3}
                                />
                            ))}
                        </div>
                    </section>

                    <div className="grid min-w-0 grid-cols-1 gap-3 @min-[44rem]/home-overview:grid-cols-2">
                        <HomeTabChartCard
                            option={retentionChart}
                            size="supporting"
                            source="Pageviews and screen views"
                            loadPriority={4}
                        />
                        <HomeTabExplore />
                    </div>
                </>
            )}
        </div>
    )
}
