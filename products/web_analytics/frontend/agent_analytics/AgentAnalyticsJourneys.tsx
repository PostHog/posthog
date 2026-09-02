import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonCard, LemonSkeleton, LemonTable, LemonTableColumns, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyLargeNumber, percentage } from 'lib/utils/numbers'
import { tryDecodeURIComponent } from 'lib/utils/url'

import { WebAgentAnalyticsQueryType } from '~/queries/schema/schema-general'

import { EMPTY_JOURNEY_SUMMARY, JourneyRow, JourneySummary, NextHop, agentAnalyticsLogic } from './agentAnalyticsLogic'
import { AgentAnalyticsSection } from './AgentAnalyticsSection'
import { AgentJourneyDetail } from './AgentJourneyDetail'
import { AgentQueryError } from './AgentQueryError'

interface SummaryStat {
    key: string
    label: string
    value: string
    description: string
}

const summaryStats = (summary: JourneySummary): SummaryStat[] => [
    {
        key: 'total',
        label: 'Journeys',
        value: humanFriendlyLargeNumber(summary.totalJourneys),
        description: 'Request sequences from one client and agent on one domain in this range.',
    },
    {
        key: 'median-pages',
        label: 'Median pages',
        value: humanFriendlyLargeNumber(summary.medianPages),
        description: 'Distinct pages requested in a typical journey.',
    },
    {
        key: 'median-duration',
        label: 'Median duration',
        value: summary.medianDurationSeconds > 0 ? humanFriendlyDuration(summary.medianDurationSeconds) : '0s',
        description: 'Time between the first and last request of a typical journey.',
    },
    {
        key: 'with-errors',
        label: 'Journeys with errors',
        value: humanFriendlyLargeNumber(summary.journeysWithErrors),
        description: 'Journeys that hit at least one 4xx or 5xx response.',
    },
]

const SummaryStatCard = ({ stat, loading }: { stat: SummaryStat; loading: boolean }): JSX.Element => (
    <LemonCard className="flex min-h-24 flex-col justify-between gap-2" hoverEffect={false}>
        <div className="flex items-center gap-1 text-sm font-medium text-secondary">
            <span>{stat.label}</span>
            <Tooltip title={stat.description}>
                <IconInfo className="text-tertiary" />
            </Tooltip>
        </div>
        {loading ? (
            <LemonSkeleton className="h-8 w-16" />
        ) : (
            <span className="text-2xl font-semibold tabular-nums">{stat.value}</span>
        )}
    </LemonCard>
)

const journeyColumns = (openJourney: (journey: JourneyRow) => void): LemonTableColumns<JourneyRow> => [
    {
        title: 'Started',
        key: 'started',
        render: (_, journey) =>
            journey.started ? <TZLabel time={journey.started} /> : <span className="text-secondary">-</span>,
    },
    {
        title: 'Agent',
        key: 'agent',
        render: (_, journey) => <span className="font-medium">{journey.agent}</span>,
    },
    {
        title: 'Domain',
        key: 'host',
        render: (_, journey) => journey.host || <span className="text-secondary">Unknown</span>,
    },
    {
        title: 'Pages',
        key: 'pages',
        align: 'right',
        render: (_, journey) => humanFriendlyLargeNumber(journey.pages),
    },
    {
        title: 'Requests',
        key: 'requests',
        align: 'right',
        render: (_, journey) => humanFriendlyLargeNumber(journey.requests),
    },
    {
        title: 'Duration',
        key: 'duration',
        align: 'right',
        render: (_, journey) => (journey.durationSeconds > 0 ? humanFriendlyDuration(journey.durationSeconds) : '0s'),
    },
    {
        title: 'Errors',
        key: 'errors',
        align: 'right',
        render: (_, journey) =>
            journey.errors > 0 ? (
                <span className="font-semibold text-danger">{humanFriendlyLargeNumber(journey.errors)}</span>
            ) : (
                <span className="text-secondary">0</span>
            ),
    },
    {
        title: '',
        key: 'actions',
        align: 'right',
        render: (_, journey) => (
            <LemonButton
                size="xsmall"
                type="secondary"
                onClick={() => openJourney(journey)}
                data-attr="agent-analytics-view-journey"
            >
                View timeline
            </LemonButton>
        ),
    },
]

const nextHopColumns = (total: number): LemonTableColumns<NextHop> => [
    {
        title: 'Next page',
        key: 'path',
        render: (_, hop) => (
            <span className="flex items-center gap-2 truncate">
                <span className="font-medium truncate">{tryDecodeURIComponent(hop.path)}</span>
                {hop.notFound > 0 ? <span className="text-danger text-xs font-semibold">404</span> : null}
            </span>
        ),
    },
    {
        title: 'Requests',
        key: 'requests',
        align: 'right',
        render: (_, hop) => humanFriendlyLargeNumber(hop.requests),
    },
    {
        title: 'Share on page',
        key: 'share',
        align: 'right',
        render: (_, hop) => (total > 0 ? percentage(hop.requests / total, 0) : '-'),
    },
]

export const AgentAnalyticsJourneys = (): JSX.Element => {
    const {
        journeySummary,
        journeySummaryError,
        journeySummaryLoading,
        journeys,
        journeysLoading,
        journeysError,
        resultPaginations,
        nextHops,
        nextHopsLoading,
        nextHopsError,
    } = useValues(agentAnalyticsLogic)
    const { setSelectedJourneyKey, loadJourneySummary, loadJourneys, loadNextHops } = useActions(agentAnalyticsLogic)

    const openJourney = (journey: JourneyRow): void => setSelectedJourneyKey(journey.journeyKey)
    const nextHopTotal = nextHops.reduce((sum, hop) => sum + hop.requests, 0)

    return (
        <div className="flex flex-col gap-6">
            <AgentAnalyticsSection
                title="Journeys"
                description="A journey is a run of requests from one client and agent on one domain. Journeys are inferred: a new one starts after 30 minutes of inactivity. A shared agent IP can mix several clients, so this does not represent a conversation."
            >
                <AgentQueryError
                    error={journeySummaryError}
                    subject="journey summaries"
                    onRetry={loadJourneySummary}
                    loading={journeySummaryLoading}
                >
                    <div className="@container">
                        <div className="grid grid-cols-2 gap-3 @md:grid-cols-3 @3xl:grid-cols-5">
                            {summaryStats(journeySummary ?? EMPTY_JOURNEY_SUMMARY).map((stat) => (
                                <SummaryStatCard key={stat.key} stat={stat} loading={!journeySummary} />
                            ))}
                        </div>
                    </div>
                </AgentQueryError>
            </AgentAnalyticsSection>

            <AgentAnalyticsSection
                title="Recent journeys"
                description="The most recent request sequences, newest first. Open one to see its timeline and how each step connects."
            >
                <AgentQueryError
                    error={journeysError}
                    subject="journeys"
                    onRetry={loadJourneys}
                    loading={journeysLoading}
                >
                    <LemonTable
                        columns={journeyColumns(openJourney)}
                        dataSource={journeys}
                        loading={journeysLoading}
                        size="small"
                        nouns={['journey', 'journeys']}
                        pagination={resultPaginations[WebAgentAnalyticsQueryType.Journeys]}
                        emptyState="No agent journeys were found in this range. Connect server-side HTTP logs, widen the date range, or include AI crawlers."
                    />
                </AgentQueryError>
            </AgentAnalyticsSection>

            <AgentAnalyticsSection
                title="Requests after llms.txt"
                description="The first different page requested by the same agent client within 30 minutes of fetching llms.txt."
            >
                <AgentQueryError
                    error={nextHopsError}
                    subject="requests after llms.txt"
                    onRetry={loadNextHops}
                    loading={nextHopsLoading}
                >
                    <LemonTable
                        columns={nextHopColumns(nextHopTotal)}
                        dataSource={nextHops}
                        loading={nextHopsLoading}
                        size="small"
                        nouns={['page', 'pages']}
                        pagination={resultPaginations[WebAgentAnalyticsQueryType.Transitions]}
                        emptyState={
                            <span className="text-secondary">
                                No requests after <Link to="https://llmstxt.org/">llms.txt</Link> were captured. Connect
                                server-side HTTP logs to include agents that do not run JavaScript.
                            </span>
                        }
                    />
                </AgentQueryError>
            </AgentAnalyticsSection>

            <AgentJourneyDetail />
        </div>
    )
}
