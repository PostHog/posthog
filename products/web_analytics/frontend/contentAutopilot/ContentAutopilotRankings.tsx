import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner, LemonButton, LemonCard, LemonSkeleton, LemonTable, Link } from '@posthog/lemon-ui'
import { TimeSeriesLineChart } from '@posthog/quill-charts'
import type { Series, TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { percentage } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'
import { parseWebAnalyticsURL } from 'scenes/web-analytics/common'
import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'

import type {
    AEORankedBrandApi,
    AEORankedDomainApi,
    AEORankedPageApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import { pageReportPath } from '../pageReports/pageReportsUtils'
import { ContentAutopilotKpiDelta } from './ContentAutopilotKpiDelta'
import { contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotPromptsDisabled } from './ContentAutopilotPromptsDisabled'
import { contentAutopilotRankingsLogic } from './contentAutopilotRankingsLogic'
import { ContentAutopilotSiteLabel } from './ContentAutopilotSiteLabel'
import { visibilityChange } from './rankingsReport'
import { brandedAnswersNote, filtersHeading, segmentPrompts } from './utils'

const CHART_CONFIG: TimeSeriesLineChartConfig = {
    xAxis: { interval: 'day' },
    yAxis: { format: 'percentage_scaled', showGrid: true },
    legend: { show: true },
    showCrosshair: true,
    // Straight segments, because a curve invents values between days.
    curve: 'linear',
}

const VisibilityChart = (): JSX.Element | null => {
    const { chart } = useValues(contentAutopilotRankingsLogic)
    const theme = useChartTheme()
    const series = useMemo<Series[]>(
        () => (chart?.series ?? []).map(({ domain, label, data }) => ({ key: domain, label, data })),
        [chart]
    )
    if (!chart) {
        return null
    }
    return (
        <div className="h-80 min-w-0 flex flex-col p-2">
            <TimeSeriesLineChart series={series} labels={chart.labels} theme={theme} config={CHART_CONFIG} />
        </div>
    )
}

export const ContentAutopilotRankings = (): JSX.Element => {
    const { rankings, rankingsLoading, rankingsError } = useValues(contentAutopilotRankingsLogic)
    const { loadRankings } = useActions(contentAutopilotRankingsLogic)
    const { setWorkspaceTab } = useActions(contentAutopilotLogic)

    if (rankingsError === 'forbidden') {
        return <ContentAutopilotPromptsDisabled />
    }
    if (rankingsError === 'failed') {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: loadRankings, loading: rankingsLoading }}
            >
                Couldn't load the rankings. Try again, and if it keeps happening contact support.
            </LemonBanner>
        )
    }
    if (!rankings) {
        return <LemonSkeleton className="h-32 w-full" />
    }
    const header = (
        <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0 flex-1 basis-80">
                <h4 className="m-0">{filtersHeading(rankings)}</h4>
                <p className="m-0 text-xs text-muted" data-attr="content-autopilot-rankings-answers">
                    {brandedAnswersNote(rankings.branded, rankings.answers)} Visibility is the share of those answers
                    that name a brand or cite its site.{' '}
                    {rankings.competitors_confirmed ? (
                        <>
                            Competitors are the ones you confirmed in{' '}
                            <Link to={urls.settings('environment-web-analytics', 'ai-visibility-brands')}>
                                AI visibility brands
                            </Link>
                            .
                        </>
                    ) : (
                        <>
                            Competitors are guessed from the sites the engines cite most.{' '}
                            <Link
                                to={urls.settings('environment-web-analytics', 'ai-visibility-brands')}
                                data-attr="content-autopilot-rankings-confirm-competitors"
                            >
                                Confirm your competitors
                            </Link>{' '}
                            to rank against them by name.
                        </>
                    )}
                </p>
            </div>
        </div>
    )
    const narrowed = rankings.engine !== null || rankings.topic !== null
    if (rankings.answers === 0 && (narrowed || rankings.branded !== 'all')) {
        return (
            <section className="flex flex-col gap-4" data-attr="content-autopilot-rankings">
                {header}
                <LemonCard hoverEffect={false} className="p-4" data-attr="content-autopilot-rankings-segment-empty">
                    <h4 className="m-0">
                        No answers to {segmentPrompts(rankings.branded)} in the last {rankings.days} days
                        {narrowed ? ' that match these filters' : ''}
                    </h4>
                    <p className="m-0 mt-1 text-muted">Choose other filters above to see the other answers.</p>
                </LemonCard>
            </section>
        )
    }
    if (rankings.answers === 0) {
        return (
            <LemonCard hoverEffect={false} className="p-4" data-attr="content-autopilot-rankings-empty">
                <h4 className="m-0">No answers yet</h4>
                <p className="m-0 mt-1 text-muted">
                    Rankings compare the answers to your prompts. Once you track prompts, the daily run fills this in.
                </p>
                <LemonButton
                    type="secondary"
                    size="small"
                    className="mt-3"
                    onClick={() => setWorkspaceTab('prompts')}
                    data-attr="content-autopilot-rankings-empty-prompts"
                >
                    Go to prompts
                </LemonButton>
            </LemonCard>
        )
    }

    return (
        <section className="@container/rankings flex flex-col gap-4" data-attr="content-autopilot-rankings">
            {header}
            <div className="grid grid-cols-1 @5xl/rankings:grid-cols-2 gap-4">
                <PagePerformanceCard className="min-w-0">
                    <PagePerformanceCardHeader title="Visibility" />
                    <VisibilityChart />
                </PagePerformanceCard>
                <PagePerformanceCard className="min-w-0">
                    <PagePerformanceCardHeader title="Brands" />
                    <div className="overflow-x-auto" data-attr="content-autopilot-rankings-brands">
                        <LemonTable<AEORankedBrandApi>
                            size="small"
                            embedded
                            dataSource={rankings.brands}
                            rowKey="domain"
                            rowStatus={(brand) => (brand.is_target ? 'highlighted' : null)}
                            columns={[
                                {
                                    title: '#',
                                    key: 'rank',
                                    width: 0,
                                    render: (_, brand) => (
                                        <span className="tabular-nums text-muted">
                                            {rankings.brands.indexOf(brand) + 1}
                                        </span>
                                    ),
                                },
                                {
                                    title: 'Brand',
                                    key: 'domain',
                                    render: (_, brand) => {
                                        const named = rankings.competitors_confirmed && !brand.is_target
                                        return (
                                            <span className="flex flex-col min-w-0">
                                                <ContentAutopilotSiteLabel
                                                    domain={brand.domain}
                                                    isTarget={brand.is_target}
                                                >
                                                    {named ? brand.name : brand.domain}
                                                </ContentAutopilotSiteLabel>
                                                {named ? (
                                                    <span className="pl-6 text-xs text-muted">{brand.domain}</span>
                                                ) : null}
                                            </span>
                                        )
                                    },
                                },
                                {
                                    title: 'Visibility',
                                    key: 'visibility',
                                    align: 'right',
                                    render: (_, brand) => (
                                        <span className="tabular-nums">
                                            {brand.visibility === null ? '-' : percentage(brand.visibility, 1)}
                                        </span>
                                    ),
                                },
                                {
                                    title: 'Change',
                                    key: 'previous_visibility',
                                    align: 'right',
                                    tooltip: `Compared with the ${rankings.days} days before, in percentage points.`,
                                    render: (_, brand) => {
                                        const change = visibilityChange(brand.visibility, brand.previous_visibility)
                                        if (change === null) {
                                            return <span className="text-muted">-</span>
                                        }
                                        return (
                                            <ContentAutopilotKpiDelta
                                                delta={{
                                                    label:
                                                        change === 0
                                                            ? 'No change'
                                                            : `${change > 0 ? '+' : ''}${change} pts`,
                                                    direction: change > 0 ? 'up' : change < 0 ? 'down' : 'flat',
                                                    tooltip: `${change > 0 ? '+' : ''}${change} percentage points against the ${rankings.days} days before`,
                                                }}
                                            />
                                        )
                                    },
                                },
                                {
                                    title: 'Positive sentiment',
                                    key: 'positive_share',
                                    align: 'right',
                                    tooltip:
                                        'Share of answers about your brand with a positive tone. Scored for your brand only.',
                                    render: (_, brand) => (
                                        <span className="tabular-nums">
                                            {brand.positive_share === null ? '-' : percentage(brand.positive_share, 0)}
                                        </span>
                                    ),
                                },
                            ]}
                        />
                    </div>
                </PagePerformanceCard>
            </div>
            <div className="grid grid-cols-1 @3xl/rankings:grid-cols-2 gap-4">
                <PagePerformanceCard className="min-w-0">
                    <PagePerformanceCardHeader title="Sites the engines cite most" />
                    <div className="overflow-x-auto" data-attr="content-autopilot-rankings-domains">
                        <LemonTable<AEORankedDomainApi>
                            size="small"
                            embedded
                            dataSource={rankings.top_domains}
                            rowKey="domain"
                            columns={[
                                {
                                    title: 'Site',
                                    key: 'domain',
                                    render: (_, domain) => (
                                        <ContentAutopilotSiteLabel
                                            domain={domain.domain}
                                            isTarget={domain.is_target}
                                            isCompetitor={domain.is_competitor}
                                        />
                                    ),
                                },
                                {
                                    title: 'Cited in',
                                    key: 'share_of_answers',
                                    align: 'right',
                                    tooltip: 'Share of answers that link to at least one page on the site.',
                                    render: (_, domain) => (
                                        <span className="tabular-nums">{percentage(domain.share_of_answers, 1)}</span>
                                    ),
                                },
                                {
                                    title: 'Pages',
                                    key: 'urls',
                                    align: 'right',
                                    tooltip: 'Different pages on the site that answers cited.',
                                    render: (_, domain) => <span className="tabular-nums">{domain.urls}</span>,
                                },
                            ]}
                        />
                    </div>
                </PagePerformanceCard>
                <PagePerformanceCard className="min-w-0">
                    <PagePerformanceCardHeader title="Pages the engines cite most" />
                    <div className="overflow-x-auto" data-attr="content-autopilot-rankings-pages">
                        <LemonTable<AEORankedPageApi>
                            size="small"
                            embedded
                            dataSource={rankings.top_pages}
                            rowKey="url"
                            columns={[
                                {
                                    title: 'Page',
                                    key: 'url',
                                    render: (_, page) => (
                                        <span className="block max-w-120">
                                            <ContentAutopilotSiteLabel
                                                domain={parseWebAnalyticsURL(page.url).host ?? page.url}
                                                isTarget={page.is_target}
                                            >
                                                <Link to={page.url} target="_blank" title={page.url}>
                                                    {page.url.replace(/^https?:\/\//, '')}
                                                </Link>
                                            </ContentAutopilotSiteLabel>
                                        </span>
                                    ),
                                },
                                {
                                    title: 'Cited in',
                                    key: 'share_of_answers',
                                    align: 'right',
                                    tooltip: 'Share of answers that link to this page.',
                                    render: (_, page) => (
                                        <span className="tabular-nums">{percentage(page.share_of_answers, 1)}</span>
                                    ),
                                },
                                {
                                    key: 'page_report',
                                    // Only your own pages have traffic in web analytics to report on.
                                    render: (_, page) =>
                                        page.is_target ? (
                                            <LemonButton
                                                size="xsmall"
                                                type="secondary"
                                                className="whitespace-nowrap"
                                                to={pageReportPath(page.url)}
                                                tooltip="See this page's traffic, including visits from AI assistants"
                                                data-attr="content-autopilot-rankings-page-report"
                                            >
                                                Page report
                                            </LemonButton>
                                        ) : null,
                                },
                            ]}
                        />
                    </div>
                </PagePerformanceCard>
            </div>
        </section>
    )
}
