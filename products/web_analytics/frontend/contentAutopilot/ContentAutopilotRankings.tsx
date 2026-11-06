import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner, LemonButton, LemonCard, LemonSkeleton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'
import { TimeSeriesLineChart } from '@posthog/quill-charts'
import type { Series, TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'

import type {
    AEORankedBrandApi,
    AEORankedDomainApi,
    AEORankedPageApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import { contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotPromptsDisabled } from './ContentAutopilotPromptsDisabled'
import { RANKINGS_DAYS, contentAutopilotRankingsLogic } from './contentAutopilotRankingsLogic'
import { visibilityChange } from './rankingsReport'

const CHART_CONFIG: TimeSeriesLineChartConfig = {
    xAxis: { interval: 'day' },
    yAxis: { format: 'percentage_scaled', showGrid: true },
    legend: { show: true },
    showCrosshair: true,
    // Straight segments, because a curve invents values between days.
    curve: 'linear',
}

const SiteTag = ({ isTarget, isCompetitor }: { isTarget: boolean; isCompetitor: boolean }): JSX.Element | null =>
    isTarget ? (
        <LemonTag type="success" size="small">
            Your site
        </LemonTag>
    ) : isCompetitor ? (
        <LemonTag type="warning" size="small">
            Competitor
        </LemonTag>
    ) : null

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
            <div>
                <h4 className="m-0">Last {RANKINGS_DAYS} days, all engines</h4>
                <p className="m-0 text-xs text-muted">
                    Visibility is the share of {pluralize(rankings.answers, 'answer')} that name a brand or cite its
                    site. Competitors are the brands behind the sites the engines cite most, matched by the name in
                    their domain, so a name that is also a common word can count extra answers.
                </p>
            </div>
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
                                    render: (_, brand) => (
                                        <span className="flex items-center gap-2 font-semibold">
                                            {brand.domain}
                                            <SiteTag isTarget={brand.is_target} isCompetitor={false} />
                                        </span>
                                    ),
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
                                    tooltip: `Compared with the ${RANKINGS_DAYS} days before, in percentage points.`,
                                    render: (_, brand) => {
                                        const change = visibilityChange(brand.visibility, brand.previous_visibility)
                                        if (change === null) {
                                            return <span className="text-muted">-</span>
                                        }
                                        return (
                                            <LemonTag
                                                size="small"
                                                type={change > 0 ? 'success' : change < 0 ? 'danger' : 'default'}
                                            >
                                                {change > 0 ? '+' : ''}
                                                {change} pts
                                            </LemonTag>
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
                                        <span className="flex items-center gap-2 font-semibold">
                                            {domain.domain}
                                            <SiteTag isTarget={domain.is_target} isCompetitor={domain.is_competitor} />
                                        </span>
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
                                        <span className="flex items-center gap-2 min-w-0 max-w-120">
                                            <Link to={page.url} target="_blank" className="truncate" title={page.url}>
                                                {page.url.replace(/^https?:\/\//, '')}
                                            </Link>
                                            <SiteTag isTarget={page.is_target} isCompetitor={false} />
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
                            ]}
                        />
                    </div>
                </PagePerformanceCard>
            </div>
        </section>
    )
}
