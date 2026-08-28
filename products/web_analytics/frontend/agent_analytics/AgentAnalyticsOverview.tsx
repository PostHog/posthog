import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonSkeleton,
    LemonTag,
    LemonTable,
    LemonTableColumns,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyLargeNumber, percentage } from 'lib/utils/numbers'
import { tryDecodeURIComponent } from 'lib/utils/url'

import {
    AgentIssue,
    EMPTY_JOURNEY_SUMMARY,
    JourneySummary,
    OverviewStats,
    PageRead,
    agentAnalyticsLogic,
    changePct,
} from './agentAnalyticsLogic'
import { AgentAnalyticsSection } from './AgentAnalyticsSection'
import { AgentIssueChangeIndicator, ChangeSentiment } from './AgentIssueChangeIndicator'
import { AgentIssueTypeTag } from './AgentIssueTypeTag'
import { AgentQueryError } from './AgentQueryError'

interface OverviewMetric {
    key: string
    label: string
    description: string
    value: number | null
    previous: number | null
    sentiment: ChangeSentiment
}

const overviewMetrics = (overview: OverviewStats | null, hasConversionGoal: boolean): OverviewMetric[] => [
    {
        key: 'active-clients',
        label: 'Active agent clients',
        description: 'Distinct agent client identifiers observed in server requests or client navigations.',
        value: overview?.activeClients ?? 0,
        previous: overview?.activeClientsPrev ?? null,
        sentiment: 'neutral',
    },
    {
        key: 'agent-families',
        label: 'Agent families',
        description: 'Distinct classified agent names observed in this period.',
        value: overview?.agentFamilies ?? 0,
        previous: null,
        sentiment: 'neutral',
    },
    {
        key: 'server-requests',
        label: 'Server requests',
        description: 'Agent HTTP requests captured by server-side HTTP logs.',
        value: overview?.serverRequests ?? 0,
        previous: overview?.serverRequestsPrev ?? null,
        sentiment: 'neutral',
    },
    {
        key: 'client-navigations',
        label: 'Client navigations',
        description: 'Agent pageviews and screen events captured by client-side tracking.',
        value: overview?.clientNavigations ?? 0,
        previous: overview?.clientNavigationsPrev ?? null,
        sentiment: 'neutral',
    },
    {
        key: '4xx-responses',
        label: 'Client errors',
        description: 'Agent requests that received a 4xx response.',
        value: overview?.clientErrors ?? 0,
        previous: overview?.clientErrorsPrev ?? null,
        sentiment: 'lower-is-better',
    },
    {
        key: 'wasted-fetches',
        label: 'Repeated fetches',
        description: 'Markdown requests made within 30 minutes of an HTML request for the same page and client.',
        value: overview?.wasted ?? 0,
        previous: overview?.wastedPrev ?? null,
        sentiment: 'lower-is-better',
    },
    {
        key: 'converted-clients',
        label: 'Converted agent clients',
        description: 'Agent clients followed by the selected conversion goal within 24 hours.',
        value: hasConversionGoal ? (overview?.convertedClients ?? 0) : null,
        previous: hasConversionGoal ? (overview?.convertedClientsPrev ?? null) : null,
        sentiment: 'higher-is-better',
    },
]

const OverviewMetricCard = ({ metric, loading }: { metric: OverviewMetric; loading: boolean }): JSX.Element => (
    <LemonCard
        className="flex min-h-24 flex-col justify-between gap-3"
        hoverEffect={false}
        data-attr={`agent-analytics-metric-${metric.key}`}
    >
        <div className="flex items-center gap-1 text-sm font-medium text-secondary">
            <span>{metric.label}</span>
            <Tooltip title={metric.description}>
                <IconInfo className="text-tertiary" />
            </Tooltip>
        </div>
        {loading ? (
            <LemonSkeleton className="h-8 w-20" />
        ) : metric.value === null ? (
            <>
                <span className="text-lg font-semibold text-secondary">Not set</span>
                <span className="text-xs text-tertiary">Select a conversion goal</span>
            </>
        ) : (
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-2xl font-semibold tabular-nums">{humanFriendlyLargeNumber(metric.value)}</span>
                <AgentIssueChangeIndicator
                    changePct={changePct(metric.value, metric.previous)}
                    sentiment={metric.sentiment}
                />
            </div>
        )}
    </LemonCard>
)

const markdownShare = (page: PageRead): number => {
    const total = page.mdFetches + page.htmlFetches
    return total > 0 ? page.mdFetches / total : 0
}

const whatAgentsReadColumns: LemonTableColumns<PageRead> = [
    {
        title: 'Page',
        key: 'page',
        render: (_, page) => <span className="font-medium truncate">{tryDecodeURIComponent(page.page)}</span>,
    },
    {
        title: 'Requests',
        key: 'fetches',
        align: 'right',
        render: (_, page) => humanFriendlyLargeNumber(page.fetches),
    },
    {
        title: 'Response formats',
        key: 'md',
        render: (_, page) => {
            const share = markdownShare(page)
            return (
                <div className="flex min-w-36 flex-col gap-1">
                    <div className="flex items-center gap-2">
                        <LemonProgress className="w-20" percent={share * 100} />
                        <span className="text-xs font-medium tabular-nums">{percentage(share, 0)} markdown</span>
                    </div>
                    <span className="text-xs text-tertiary">
                        {humanFriendlyLargeNumber(page.mdFetches)} markdown ·{' '}
                        {humanFriendlyLargeNumber(page.htmlFetches)} HTML
                    </span>
                </div>
            )
        },
    },
    {
        title: 'Repeated requests',
        key: 'waste',
        align: 'right',
        render: (_, page) =>
            page.pairedClients > 0 ? (
                <Tooltip
                    title={`${humanFriendlyLargeNumber(page.pairedClients)} agent ${page.pairedClients === 1 ? 'client fetched' : 'clients fetched'} both the HTML and markdown versions of this page.`}
                >
                    <LemonTag type="warning" size="small">
                        {humanFriendlyLargeNumber(page.pairedClients)} {page.pairedClients === 1 ? 'client' : 'clients'}
                    </LemonTag>
                </Tooltip>
            ) : (
                <span className="text-secondary">-</span>
            ),
    },
]

const journeySummaryHighlights = (summary: JourneySummary): { key: string; label: string; value: string }[] => [
    { key: 'total', label: 'Journeys', value: humanFriendlyLargeNumber(summary.totalJourneys) },
    { key: 'median-pages', label: 'Median pages', value: humanFriendlyLargeNumber(summary.medianPages) },
    {
        key: 'median-duration',
        label: 'Median duration',
        value: summary.medianDurationSeconds > 0 ? humanFriendlyDuration(summary.medianDurationSeconds) : '0s',
    },
    { key: 'with-errors', label: 'With errors', value: humanFriendlyLargeNumber(summary.journeysWithErrors) },
]

export const AgentAnalyticsOverview = (): JSX.Element => {
    const {
        overview,
        overviewLoading,
        overviewError,
        conversionGoal,
        topIssues,
        contentGapIssuesLoading,
        contentGapIssuesError,
        whatAgentsRead,
        whatAgentsReadLoading,
        whatAgentsReadError,
        journeySummary,
        journeySummaryLoading,
        journeySummaryError,
    } = useValues(agentAnalyticsLogic)
    const { setView, setSelectedIssueKey, loadOverview, loadIssues, loadWhatAgentsRead, loadJourneySummary } =
        useActions(agentAnalyticsLogic)

    const openIssue = (issue: AgentIssue): void => {
        setView('issues')
        setSelectedIssueKey(issue.key)
    }

    return (
        <div className="flex flex-col gap-6">
            <AgentAnalyticsSection
                title="Key metrics"
                description="Agent activity and request quality for the selected period."
                right={
                    overview && overview.excludedRequests > 0 ? (
                        <Tooltip title="Static asset requests, like images, stylesheets, and fonts, are excluded from content analysis.">
                            <LemonTag type="muted" icon={<IconInfo />}>
                                {humanFriendlyLargeNumber(overview.excludedRequests)} static asset requests excluded
                            </LemonTag>
                        </Tooltip>
                    ) : undefined
                }
            >
                <AgentQueryError
                    error={overviewError}
                    subject="the overview"
                    onRetry={loadOverview}
                    loading={overviewLoading}
                >
                    <div className="@container">
                        <div className="grid grid-cols-1 gap-3 @md:grid-cols-2 @3xl:grid-cols-4">
                            {overviewMetrics(overview, conversionGoal !== null).map((metric) => (
                                <OverviewMetricCard key={metric.key} metric={metric} loading={!overview} />
                            ))}
                        </div>
                    </div>
                </AgentQueryError>
                {overview && overview.serverRequests > 0 && overview.statusObserved === 0 ? (
                    <LemonBanner type="info">
                        Server requests were captured without response status codes. Client error, missing page, and
                        successful page reports need the <code>proxy_status_code</code> property.
                    </LemonBanner>
                ) : overview && overview.serverRequests === 0 && overview.clientNavigations > 0 ? (
                    <LemonBanner type="info">
                        Client navigations are available, but server requests are not. Connect server-side HTTP logs to
                        analyze response status, content formats, and llms.txt requests without double-counting
                        navigations.
                    </LemonBanner>
                ) : null}
            </AgentAnalyticsSection>

            <AgentAnalyticsSection
                title="Needs attention"
                description="Issues ranked by the number of agent requests they affect."
                right={
                    <LemonButton size="small" type="secondary" onClick={() => setView('issues')}>
                        View all issues
                    </LemonButton>
                }
            >
                <AgentQueryError
                    error={contentGapIssuesError}
                    subject="agent issues"
                    onRetry={loadIssues}
                    loading={contentGapIssuesLoading}
                >
                    {contentGapIssuesLoading && topIssues.length === 0 ? (
                        <div className="flex min-h-20 items-center justify-center">
                            <Spinner />
                        </div>
                    ) : topIssues.length === 0 ? (
                        <LemonCard hoverEffect={false} className="text-secondary">
                            No agent issues were found in this range. Widen the date range or include AI crawlers.
                        </LemonCard>
                    ) : (
                        <LemonCard hoverEffect={false} className="divide-y divide-primary overflow-hidden p-0">
                            {topIssues.map((issue) => (
                                <LemonButton
                                    key={issue.key}
                                    fullWidth
                                    onClick={() => openIssue(issue)}
                                    size="small"
                                    type="tertiary"
                                    className="rounded-none px-3 py-2"
                                    data-attr="agent-analytics-open-issue"
                                >
                                    <span className="flex w-full min-w-0 flex-wrap items-center justify-between gap-3 text-left">
                                        <span className="flex min-w-0 items-start gap-2">
                                            <AgentIssueTypeTag type={issue.type} />
                                            <span className="flex min-w-0 flex-col gap-0.5">
                                                <span className="truncate font-medium">{issue.title}</span>
                                                <span className="truncate text-xs text-secondary">
                                                    {issue.subtitle}
                                                </span>
                                            </span>
                                        </span>
                                        <span className="flex items-center gap-2 shrink-0 text-secondary">
                                            <span>{humanFriendlyLargeNumber(issue.demand)}</span>
                                            <AgentIssueChangeIndicator changePct={issue.changePct} />
                                        </span>
                                    </span>
                                </LemonButton>
                            ))}
                        </LemonCard>
                    )}
                </AgentQueryError>
            </AgentAnalyticsSection>

            <AgentAnalyticsSection
                title="What agents read"
                description="The five most requested pages from server-side agent traffic."
            >
                <AgentQueryError
                    error={whatAgentsReadError}
                    subject="page requests"
                    onRetry={loadWhatAgentsRead}
                    loading={whatAgentsReadLoading}
                >
                    <LemonTable
                        columns={whatAgentsReadColumns}
                        dataSource={whatAgentsRead}
                        loading={whatAgentsReadLoading}
                        size="small"
                        emptyState="No agent page requests were found in this range. Widen the date range or include AI crawlers."
                    />
                </AgentQueryError>
            </AgentAnalyticsSection>

            <AgentAnalyticsSection
                title="Agent journeys"
                description="How agents move through the site across a sequence of requests."
                right={
                    <LemonButton size="small" type="secondary" onClick={() => setView('journeys')}>
                        View journeys
                    </LemonButton>
                }
            >
                <AgentQueryError
                    error={journeySummaryError}
                    subject="agent journeys"
                    onRetry={loadJourneySummary}
                    loading={journeySummaryLoading}
                >
                    <div className="@container">
                        <div className="grid grid-cols-2 gap-3 @md:grid-cols-4">
                            {journeySummaryHighlights(journeySummary ?? EMPTY_JOURNEY_SUMMARY).map((highlight) => (
                                <LemonCard
                                    key={highlight.key}
                                    className="flex min-h-20 flex-col justify-between gap-2"
                                    hoverEffect={false}
                                >
                                    <span className="text-sm font-medium text-secondary">{highlight.label}</span>
                                    {journeySummary ? (
                                        <span className="text-2xl font-semibold tabular-nums">{highlight.value}</span>
                                    ) : (
                                        <LemonSkeleton className="h-8 w-16" />
                                    )}
                                </LemonCard>
                            ))}
                        </div>
                    </div>
                </AgentQueryError>
            </AgentAnalyticsSection>
        </div>
    )
}
