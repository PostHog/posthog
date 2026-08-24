import { useActions, useValues } from 'kea'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { WebAgentAnalyticsQueryType, WebAgentContentGrouping } from '~/queries/schema/schema-general'

import { AgentIssue, agentAnalyticsLogic } from './agentAnalyticsLogic'
import { AgentAnalyticsSection } from './AgentAnalyticsSection'
import { AgentIssueChangeIndicator } from './AgentIssueChangeIndicator'
import { AgentIssueDetail } from './AgentIssueDetail'
import { AgentIssueTypeTag } from './AgentIssueTypeTag'
import { agentIssueDemandLabel } from './agentIssueUtils'
import { AgentQueryError } from './AgentQueryError'

const GROUPING_OPTIONS: { value: WebAgentContentGrouping; label: string }[] = [
    { value: WebAgentContentGrouping.Normalized, label: 'Group similar URLs' },
    { value: WebAgentContentGrouping.Exact, label: 'Exact URLs' },
]

const issueColumns = (onOpen: (issue: AgentIssue) => void): LemonTableColumns<AgentIssue> => [
    {
        title: 'Issue',
        key: 'issue',
        render: (_, issue) => (
            <div className="flex flex-col gap-1 py-1">
                <div className="flex items-center gap-2 min-w-0">
                    <AgentIssueTypeTag type={issue.type} />
                    <LemonButton
                        type="tertiary"
                        size="small"
                        noPadding
                        className="font-semibold truncate"
                        onClick={() => onOpen(issue)}
                        data-attr="agent-analytics-open-issue"
                    >
                        <span className="flex min-w-0 items-center gap-1">
                            <span className="truncate">{issue.title}</span>
                            <IconChevronRight className="shrink-0 text-tertiary" />
                        </span>
                    </LemonButton>
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
                    <span className="font-medium whitespace-nowrap">{agentIssueDemandLabel(issue)}</span>
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
    const { issues, issuesLoading, issuesError, selectedIssue, resultPaginations, contentGrouping } =
        useValues(agentAnalyticsLogic)
    const { setSelectedIssueKey, setContentGrouping, loadIssues } = useActions(agentAnalyticsLogic)

    if (selectedIssue) {
        return <AgentIssueDetail />
    }

    return (
        <AgentAnalyticsSection
            title="Issues"
            description="Missing pages, repeated format requests, and malformed paths ranked by affected agent requests."
            right={
                <LemonSegmentedButton
                    size="small"
                    value={contentGrouping}
                    onChange={setContentGrouping}
                    options={GROUPING_OPTIONS}
                    data-attr="agent-analytics-content-grouping"
                />
            }
        >
            <AgentQueryError
                error={issuesError}
                message="Could not load agent issues. Try again. If it keeps happening, contact support."
                onRetry={loadIssues}
                loading={issuesLoading}
            >
                <LemonTable
                    columns={issueColumns((issue) => setSelectedIssueKey(issue.key))}
                    dataSource={issues}
                    loading={issuesLoading}
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
