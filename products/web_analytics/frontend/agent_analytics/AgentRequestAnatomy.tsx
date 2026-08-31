import { useActions, useValues } from 'kea'

import { LemonTable, LemonTableColumns, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyLargeNumber, percentage } from 'lib/utils/numbers'

import { WebAgentAnalyticsQueryType } from '~/queries/schema/schema-general'

import { RequestAnatomyRow, agentAnalyticsLogic } from './agentAnalyticsLogic'
import { AgentAnalyticsSection } from './AgentAnalyticsSection'
import { AgentQueryError } from './AgentQueryError'

const markdownShare = (row: RequestAnatomyRow): number => (row.requests > 0 ? row.requestedMarkdown / row.requests : 0)

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

    return (
        <AgentAnalyticsSection
            title="Request anatomy"
            description="How each agent asks for content. Format is read from the request URL."
        >
            <AgentQueryError
                error={requestAnatomyError}
                subject="request anatomy"
                onRetry={loadRequestAnatomy}
                loading={requestAnatomyLoading}
            >
                <LemonTable
                    columns={anatomyColumns}
                    dataSource={requestAnatomy}
                    loading={requestAnatomyLoading}
                    size="small"
                    nouns={['agent', 'agents']}
                    pagination={resultPaginations[WebAgentAnalyticsQueryType.RequestAnatomy]}
                    emptyState="No per-agent request data was found. Connect server-side HTTP logs, widen the date range, or include AI crawlers."
                />
            </AgentQueryError>
        </AgentAnalyticsSection>
    )
}
