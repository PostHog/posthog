import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconExternal } from '@posthog/icons'
import { Button, cn, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle, Text } from '@posthog/quill'
import { TimeSeriesLineChart } from '@posthog/quill-charts'
import type { Series, TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils/strings'
import { parseWebAnalyticsURL } from 'scenes/web-analytics/common'

import type {
    AEORankedBrandApi,
    AEORankedDomainApi,
    AEORankedPageApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import { pageReportPath } from '../pageReports/pageReportsUtils'
import { AiVisibilityBanner } from './AiVisibilityBanner'
import { AiVisibilityCard } from './AiVisibilityCard'
import { AiVisibilityTable } from './AiVisibilityTable'
import { ContentAutopilotCitationsLink } from './ContentAutopilotCitationsLink'
import { ContentAutopilotKpiDelta } from './ContentAutopilotKpiDelta'
import { contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotPromptsDisabled } from './ContentAutopilotPromptsDisabled'
import { contentAutopilotRankingsLogic } from './contentAutopilotRankingsLogic'
import { ContentAutopilotRankingsSkeleton } from './ContentAutopilotRankingsSkeleton'
import { ContentAutopilotRateBar } from './ContentAutopilotRateBar'
import { ContentAutopilotSiteLabel } from './ContentAutopilotSiteLabel'
import { visibilityChange } from './rankingsReport'
import { segmentPrompts, windowRange } from './utils'
import { MIN_TREND_DAYS } from './visibilityChart'

const CHART_CONFIG: TimeSeriesLineChartConfig = {
    // The labels are calendar days, so UTC keeps each tick and tooltip date on its own day.
    xAxis: { interval: 'day', timezone: 'UTC' },
    yAxis: { format: 'percentage_scaled', showGrid: true },
    legend: { show: true },
    showCrosshair: true,
    // Straight segments, because a curve invents values between days.
    curve: 'linear',
}

// The table's own container: a narrow tile drops these columns before anything has to scroll sideways.
const FROM_MD = 'hidden @md/ai-visibility-table:table-cell'
const FROM_XL = 'hidden @xl/ai-visibility-table:table-cell'
const FILL = 'w-full max-w-0'

const VisibilityChart = (): JSX.Element | null => {
    const { rankings, chart, rankingsLoading } = useValues(contentAutopilotRankingsLogic)
    const theme = useChartTheme()
    const series = useMemo<Series[]>(
        () =>
            (chart?.series ?? []).map(({ domain, label, colorIndex, data }) => ({
                key: domain,
                label,
                color: theme.colors[colorIndex % theme.colors.length],
                data,
            })),
        [chart, theme]
    )
    if (!chart) {
        return null
    }
    const daysOfData = new Set((rankings?.daily ?? []).filter(({ answers }) => answers > 0).map(({ date }) => date))
        .size
    return (
        <div
            className={cn('flex min-h-64 min-w-0 flex-1 flex-col', rankingsLoading && 'opacity-50')}
            aria-busy={rankingsLoading}
        >
            {daysOfData < MIN_TREND_DAYS ? (
                <Text
                    size="xs"
                    variant="muted"
                    render={<p className="m-0 pb-1" />}
                    data-attr="content-autopilot-rankings-waiting"
                >
                    Waiting for more days of data. {pluralize(daysOfData, 'day')} of {MIN_TREND_DAYS} so far.
                </Text>
            ) : null}
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
            <AiVisibilityBanner
                type="error"
                action={{ children: 'Try again', onClick: loadRankings, loading: rankingsLoading }}
            >
                Couldn't load the rankings. Try again, and if it keeps happening contact support.
            </AiVisibilityBanner>
        )
    }
    if (!rankings) {
        return <ContentAutopilotRankingsSkeleton />
    }
    const narrowed = rankings.engine !== null || rankings.topic !== null
    if (rankings.answers === 0 && (narrowed || rankings.branded !== 'all')) {
        return (
            <section className="flex flex-col gap-4" data-attr="content-autopilot-rankings">
                <Empty data-attr="content-autopilot-rankings-segment-empty">
                    <EmptyHeader>
                        <EmptyTitle>
                            No answers to {segmentPrompts(rankings.branded)} {windowRange(rankings)}
                            {narrowed ? ' that match these filters' : ''}
                        </EmptyTitle>
                        <EmptyDescription>Choose other filters above to see the other answers.</EmptyDescription>
                    </EmptyHeader>
                </Empty>
            </section>
        )
    }
    if (rankings.answers === 0) {
        return (
            <Empty data-attr="content-autopilot-rankings-empty">
                <EmptyHeader>
                    <EmptyTitle>No answers yet</EmptyTitle>
                    <EmptyDescription>
                        Rankings compare the answers to your prompts. Once you track prompts, the daily run fills this
                        in.
                    </EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                    <Button
                        variant="outline"
                        onClick={() => setWorkspaceTab('prompts')}
                        data-attr="content-autopilot-rankings-empty-prompts"
                    >
                        Go to prompts
                    </Button>
                </EmptyContent>
            </Empty>
        )
    }

    return (
        <section className="@container/rankings flex flex-col gap-4" data-attr="content-autopilot-rankings">
            <div className="grid grid-cols-1 @5xl/rankings:grid-cols-2 gap-4">
                <AiVisibilityCard title="Visibility" className="h-full">
                    <VisibilityChart />
                </AiVisibilityCard>
                <AiVisibilityCard
                    title="Brands"
                    className="h-full"
                    actions={
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setWorkspaceTab('settings')}
                            data-attr="content-autopilot-rankings-edit-competitors"
                        >
                            Edit competitors
                        </Button>
                    }
                >
                    <AiVisibilityTable<AEORankedBrandApi>
                        size="small"
                        embedded
                        loading={rankingsLoading}
                        data-attr="content-autopilot-rankings-brands"
                        emptyState="No brand was named in these answers."
                        dataSource={rankings.brands}
                        rowKey="domain"
                        rowStatus={(brand) => (brand.is_target ? 'highlighted' : null)}
                        columns={[
                            {
                                title: '#',
                                key: 'rank',
                                width: 0,
                                render: (_, brand) => (
                                    <span className="tabular-nums text-muted-foreground">
                                        {rankings.brands.indexOf(brand) + 1}
                                    </span>
                                ),
                            },
                            {
                                title: 'Brand',
                                key: 'domain',
                                className: FILL,
                                render: (_, brand) => {
                                    const named = rankings.competitors_confirmed && !brand.is_target
                                    return (
                                        <ContentAutopilotSiteLabel
                                            domain={brand.domain}
                                            isTarget={brand.is_target}
                                            subtitle={named ? brand.domain : undefined}
                                        >
                                            <ContentAutopilotCitationsLink
                                                lookup={{
                                                    kind: 'domain',
                                                    value: brand.domain,
                                                    dateFrom: rankings.window_from,
                                                    dateTo: rankings.window_to,
                                                    branded: rankings.branded,
                                                }}
                                                source="rankings-brands"
                                                // Without padding, every name starts where the domain under it does.
                                                className="px-0"
                                            >
                                                {named ? brand.name : brand.domain}
                                            </ContentAutopilotCitationsLink>
                                        </ContentAutopilotSiteLabel>
                                    )
                                },
                            },
                            {
                                title: 'Visibility',
                                key: 'visibility',
                                tooltip: 'The share of these answers that name the brand or cite its site.',
                                align: 'right',
                                render: (_, brand) => (
                                    <ContentAutopilotRateBar
                                        rate={brand.visibility}
                                        tooltip={`Out of ${pluralize(rankings.answers, 'answer')}`}
                                    />
                                ),
                            },
                            {
                                title: 'Change',
                                key: 'previous_visibility',
                                align: 'right',
                                className: FROM_MD,
                                tooltip: `Compared with the ${rankings.days} days before, in percentage points. Left blank when those days have under a quarter of this range's answers.`,
                                render: (_, brand) => {
                                    const change = visibilityChange(brand.visibility, brand.previous_visibility)
                                    if (change === null) {
                                        return <span className="text-muted-foreground">-</span>
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
                                className: FROM_XL,
                                tooltip:
                                    'Share of answers about your brand with a positive tone. Scored for your brand only.',
                                render: (_, brand) => <ContentAutopilotRateBar rate={brand.positive_share} />,
                            },
                        ]}
                    />
                </AiVisibilityCard>
            </div>
            <div className="grid grid-cols-1 @3xl/rankings:grid-cols-2 gap-4">
                <AiVisibilityCard title="Sites the engines cite most">
                    <AiVisibilityTable<AEORankedDomainApi>
                        size="small"
                        embedded
                        loading={rankingsLoading}
                        data-attr="content-autopilot-rankings-domains"
                        emptyState="No answer cited a site in this window."
                        dataSource={rankings.top_domains}
                        rowKey="domain"
                        columns={[
                            {
                                title: 'Site',
                                key: 'domain',
                                className: FILL,
                                render: (_, domain) => (
                                    <ContentAutopilotSiteLabel
                                        domain={domain.domain}
                                        isTarget={domain.is_target}
                                        isCompetitor={domain.is_competitor}
                                    >
                                        <ContentAutopilotCitationsLink
                                            lookup={{
                                                kind: 'domain',
                                                value: domain.domain,
                                                dateFrom: rankings.window_from,
                                                dateTo: rankings.window_to,
                                                branded: rankings.branded,
                                            }}
                                            source="rankings-sites"
                                        >
                                            {domain.domain}
                                        </ContentAutopilotCitationsLink>
                                    </ContentAutopilotSiteLabel>
                                ),
                            },
                            {
                                title: 'Cited in',
                                key: 'share_of_answers',
                                align: 'right',
                                tooltip: 'Share of answers that link to at least one page on the site.',
                                render: (_, domain) => <ContentAutopilotRateBar rate={domain.share_of_answers} />,
                            },
                            {
                                title: 'Pages',
                                key: 'urls',
                                align: 'right',
                                className: FROM_MD,
                                tooltip: 'Different pages on the site that answers cited.',
                                render: (_, domain) => <span className="tabular-nums">{domain.urls}</span>,
                            },
                        ]}
                    />
                </AiVisibilityCard>
                <AiVisibilityCard title="Pages the engines cite most">
                    <AiVisibilityTable<AEORankedPageApi>
                        size="small"
                        embedded
                        loading={rankingsLoading}
                        data-attr="content-autopilot-rankings-pages"
                        emptyState="No answer cited a page in this window."
                        dataSource={rankings.top_pages}
                        rowKey="url"
                        columns={[
                            {
                                title: 'Page',
                                key: 'url',
                                className: FILL,
                                render: (_, page) => (
                                    <ContentAutopilotSiteLabel
                                        domain={parseWebAnalyticsURL(page.url).host ?? page.url}
                                        isTarget={page.is_target}
                                    >
                                        <ContentAutopilotCitationsLink
                                            lookup={{
                                                kind: 'url',
                                                value: page.url,
                                                dateFrom: rankings.window_from,
                                                dateTo: rankings.window_to,
                                                branded: rankings.branded,
                                            }}
                                            source="rankings-pages"
                                            title={page.url}
                                        >
                                            {page.url.replace(/^https?:\/\//, '')}
                                        </ContentAutopilotCitationsLink>
                                    </ContentAutopilotSiteLabel>
                                ),
                            },
                            {
                                title: 'Cited in',
                                key: 'share_of_answers',
                                align: 'right',
                                tooltip: 'Share of answers that link to this page.',
                                render: (_, page) => <ContentAutopilotRateBar rate={page.share_of_answers} />,
                            },
                            {
                                key: 'page_report',
                                width: 0,
                                // Only your own pages have traffic in web analytics to report on, and the external
                                // button comes last so it lines up on every row.
                                render: (_, page) => (
                                    <span className="flex items-center justify-end gap-1">
                                        {page.is_target ? (
                                            <Button
                                                variant="outline"
                                                size="sm"
                                                nativeButton={false}
                                                render={<LinkPrimitive to={pageReportPath(page.url)} />}
                                                tooltip="See this page's traffic, including visits from AI assistants"
                                                data-attr="content-autopilot-rankings-page-report"
                                            >
                                                Page report
                                            </Button>
                                        ) : null}
                                        <Button
                                            size="icon-sm"
                                            nativeButton={false}
                                            render={<LinkPrimitive to={page.url} target="_blank" />}
                                            aria-label="Open the page"
                                            tooltip="Open the page"
                                            data-attr="content-autopilot-rankings-page-open"
                                        >
                                            <IconExternal />
                                        </Button>
                                    </span>
                                ),
                            },
                        ]}
                    />
                </AiVisibilityCard>
            </div>
        </section>
    )
}
