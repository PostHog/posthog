import { useActions, useValues } from 'kea'

import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { WebAgentAnalyticsQueryType } from '~/queries/schema/schema-general'

import { AgentIssue, agentAnalyticsLogic } from './agentAnalyticsLogic'
import { AgentAnalyticsSection } from './AgentAnalyticsSection'
import { AgentIssueChangeIndicator } from './AgentIssueChangeIndicator'
import { AgentIssueDetail } from './AgentIssueDetail'
import { AgentIssueTypeTag } from './AgentIssueTypeTag'
import { AgentQueryError } from './AgentQueryError'

const issueColumns: LemonTableColumns<AgentIssue> = [
    {
        title: 'Issue',
        key: 'issue',
        render: (_, issue) => (
            <div className="flex flex-col gap-1 py-1">
                <div className="flex items-center gap-2 min-w-0">
                    <AgentIssueTypeTag type={issue.type} />
                    <span className="truncate font-semibold">{issue.title}</span>
                </div>
                <span className="text-xs text-secondary">{issue.subtitle}</span>
            </div>
        ),
    },
    {
        title: 'Requests',
        key: 'demand',
        align: 'right',
        sorter: (a, b) => a.demand - b.demand,
        render: (_, issue) => (
            <div className="flex items-center justify-end gap-3">
                <div className="flex flex-col items-end">
                    <span className="font-medium whitespace-nowrap">{humanFriendlyLargeNumber(issue.demand)}</span>
                    <AgentIssueChangeIndicator changePct={issue.changePct} />
                </div>
            </div>
        ),
    },
    {
        title: 'Top agent',
        key: 'agent',
        render: (_, issue) => issue.topAgent ?? <span className="text-secondary">-</span>,
    },
    {
        title: 'First seen in range',
        key: 'first_seen',
        render: (_, issue) =>
            issue.firstSeen ? <TZLabel time={issue.firstSeen} /> : <span className="text-secondary">-</span>,
    },
]

export const AgentAnalyticsIssues = (): JSX.Element => {
    const { issues, contentGapIssuesLoading, contentGapIssuesError, selectedIssueKey, resultPaginations } =
        useValues(agentAnalyticsLogic)
    const { setSelectedIssueKey, loadIssues } = useActions(agentAnalyticsLogic)

    return (
        <AgentAnalyticsSection
            title="Issues"
            description="Missing pages, repeated format requests, and malformed paths ranked by affected agent requests."
        >
            <AgentQueryError
                error={contentGapIssuesError}
                subject="agent issues"
                onRetry={loadIssues}
                loading={contentGapIssuesLoading}
            >
                <LemonTable
                    columns={issueColumns}
                    dataSource={issues}
                    expandable={{
                        isRowExpanded: (issue) => issue.key === selectedIssueKey,
                        onRowExpand: (issue) => setSelectedIssueKey(issue.key),
                        onRowCollapse: () => setSelectedIssueKey(null),
                        expandedRowRender: (issue) => <AgentIssueDetail issue={issue} />,
                    }}
                    loading={contentGapIssuesLoading}
                    defaultSorting={{ columnKey: 'demand', order: -1 }}
                    emptyState="No agent issues were found in this range. Widen the date range or include AI crawlers."
                    rowKey="key"
                    nouns={['issue', 'issues']}
                    pagination={resultPaginations[WebAgentAnalyticsQueryType.Issues]}
                />
            </AgentQueryError>
        </AgentAnalyticsSection>
    )
}
