import { useActions, useValues } from 'kea'

import { LemonBanner, LemonTable, LemonTableColumns, LemonTag, LemonTagType, Link, Tooltip } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyLargeNumber, percentage } from 'lib/utils/numbers'

import { WebAgentAnalyticsQueryType } from '~/queries/schema/schema-general'

import { RequestAnatomyRow, agentAnalyticsLogic } from './agentAnalyticsLogic'
import { AgentAnalyticsSection } from './AgentAnalyticsSection'
import { AgentQueryError } from './AgentQueryError'

interface AcceptSummary {
    label: string
    tone: LemonTagType
    detail: string
}

const acceptSummary = (row: RequestAnatomyRow): AcceptSummary => {
    if (row.acceptCaptured === 0) {
        return {
            label: 'Not captured',
            tone: 'muted',
            detail: 'The Accept header was not in the logs, so we cannot report a preference.',
        }
    }
    const preferred = row.acceptMarkdownPreferred / row.acceptCaptured
    const accepted = row.acceptMarkdownAccepted / row.acceptCaptured
    const html = row.acceptHtmlOnly / row.acceptCaptured
    if (preferred >= accepted && preferred >= html) {
        return { label: 'Prefers markdown', tone: 'success', detail: `${percentage(preferred, 0)} prefer markdown` }
    }
    if (accepted >= html) {
        return { label: 'Accepts markdown', tone: 'primary', detail: `${percentage(accepted, 0)} accept markdown` }
    }
    return { label: 'HTML only', tone: 'warning', detail: `${percentage(html, 0)} ask for HTML only` }
}

const markdownShare = (row: RequestAnatomyRow): number => (row.requests > 0 ? row.requestedMarkdown / row.requests : 0)

const coverageTone = (captured: number, total: number): LemonTagType => {
    if (captured === total) {
        return 'success'
    }
    return captured > 0 ? 'warning' : 'muted'
}

const anatomyColumns: LemonTableColumns<RequestAnatomyRow> = [
    {
        title: 'Agent',
        key: 'agent',
        render: (_, row) => <span className="font-medium">{row.agent}</span>,
    },
    {
        title: 'Requests',
        key: 'requests',
        align: 'right',
        render: (_, row) => humanFriendlyLargeNumber(row.requests),
    },
    {
        title: 'Accept preference',
        key: 'accept',
        render: (_, row) => {
            const summary = acceptSummary(row)
            return (
                <Tooltip title={summary.detail}>
                    <LemonTag type={summary.tone} size="small">
                        {summary.label}
                    </LemonTag>
                </Tooltip>
            )
        },
    },
    {
        title: 'Requested format',
        key: 'requested',
        render: (_, row) => {
            const share = markdownShare(row)
            return (
                <div className="flex min-w-32 items-center gap-2">
                    <LemonProgress className="w-16" percent={share * 100} />
                    <span className="text-xs tabular-nums">{percentage(share, 0)} markdown</span>
                </div>
            )
        },
    },
    {
        title: 'Served format',
        key: 'served',
        align: 'right',
        render: (_, row) =>
            row.servedCaptured > 0 ? (
                <span className="text-xs tabular-nums">
                    {percentage(row.servedMarkdown / row.servedCaptured, 0)} markdown
                </span>
            ) : (
                <Tooltip title="The response Content-Type was not in the logs, so we cannot report what was served.">
                    <span className="text-xs text-tertiary">Not captured</span>
                </Tooltip>
            ),
    },
    {
        title: 'HTML then markdown',
        key: 'retry',
        align: 'right',
        render: (_, row) =>
            row.retryPairs > 0 ? (
                <Tooltip title="Requests where the agent fetched a page as HTML and then re-fetched its markdown twin. Advertising the markdown version avoids the second request.">
                    <LemonTag type="warning" size="small">
                        {percentage(row.retryPairs / row.requests, 0)}
                    </LemonTag>
                </Tooltip>
            ) : (
                <span className="text-secondary">-</span>
            ),
    },
    {
        title: 'Errors',
        key: 'errors',
        align: 'right',
        render: (_, row) =>
            row.errors > 0 ? (
                <span className="font-semibold text-danger">{percentage(row.errors / row.requests, 1)}</span>
            ) : (
                <span className="text-secondary">0%</span>
            ),
    },
]

export const AgentRequestAnatomy = (): JSX.Element => {
    const { requestAnatomy, requestAnatomyLoading, requestAnatomyError, resultPaginations } =
        useValues(agentAnalyticsLogic)
    const { loadRequestAnatomy } = useActions(agentAnalyticsLogic)
    const coverage = requestAnatomy.reduce(
        (totals, row) => ({
            requests: totals.requests + row.requests,
            accept: totals.accept + row.acceptCaptured,
            contentType: totals.contentType + row.servedCaptured,
        }),
        { requests: 0, accept: 0, contentType: 0 }
    )
    const anyHeadersCaptured = coverage.accept > 0 || coverage.contentType > 0

    return (
        <AgentAnalyticsSection
            title="Request anatomy"
            description="How each agent asks for and receives content. We measure what your agents actually send rather than assume behavior from a lookup table."
            right={
                !requestAnatomyLoading && coverage.requests > 0 ? (
                    <div className="flex flex-wrap items-center gap-1">
                        <LemonTag type={coverageTone(coverage.accept, coverage.requests)} size="small">
                            Accept captured for {percentage(coverage.accept / coverage.requests, 0)} on this page
                        </LemonTag>
                        <LemonTag type={coverageTone(coverage.contentType, coverage.requests)} size="small">
                            Content-Type captured for {percentage(coverage.contentType / coverage.requests, 0)} on this
                            page
                        </LemonTag>
                    </div>
                ) : undefined
            }
        >
            <AgentQueryError
                error={requestAnatomyError}
                message="Could not load request anatomy. Try again. If it keeps happening, contact support."
                onRetry={loadRequestAnatomy}
                loading={requestAnatomyLoading}
            >
                <>
                    {!requestAnatomyLoading && requestAnatomy.length > 0 && !anyHeadersCaptured ? (
                        <LemonBanner type="info">
                            The Accept header and response Content-Type are not in these logs yet, so format columns are
                            inferred from the request URL. Capture them with a{' '}
                            <Link to="https://examples.vercel.com/docs/headers/request-headers">Vercel</Link> function
                            or{' '}
                            <Link to="https://developers.cloudflare.com/logs/logpush/logpush-job/custom-fields/">
                                Cloudflare Logpush custom fields
                            </Link>{' '}
                            to measure real negotiation. We never store credentials, cookies, or arbitrary headers.
                        </LemonBanner>
                    ) : null}
                    <LemonTable
                        columns={anatomyColumns}
                        dataSource={requestAnatomy}
                        loading={requestAnatomyLoading}
                        size="small"
                        nouns={['agent', 'agents']}
                        pagination={resultPaginations[WebAgentAnalyticsQueryType.RequestAnatomy]}
                        emptyState="No per-agent request data was found. Connect server-side HTTP logs, widen the date range, or include AI crawlers."
                    />
                </>
            </AgentQueryError>
        </AgentAnalyticsSection>
    )
}
