import { useActions, useValues } from 'kea'

import { LemonInput, LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type { WorkflowEmailSendingRatesApi } from 'products/workflows/frontend/generated/api.schemas'

import { RateCell } from './RateCell'
import { WORKFLOW_LIMIT, workflowName } from './reputationUtils'
import { workflowsReputationActionsLogic } from './workflowsReputationActionsLogic'

export function ReputationWorkflowTable(): JSX.Element {
    const { tableWorkflows, tableLoading, workflowSearchFailed, workflowSnapshots, search, searchTerm } = useValues(
        workflowsReputationActionsLogic
    )
    const { setSearch } = useActions(workflowsReputationActionsLogic)

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
                <LemonInput
                    type="search"
                    placeholder="Search workflows"
                    value={search}
                    onChange={setSearch}
                    className="max-w-80"
                    data-attr="workflows-reputation-search"
                />
                {!searchTerm && workflowSnapshots.length >= WORKFLOW_LIMIT && (
                    <span className="text-secondary text-xs">
                        Showing the {WORKFLOW_LIMIT} workflows with the highest rates. Search to find any other sending
                        workflow.
                    </span>
                )}
            </div>
            <LemonTable
                dataSource={[...tableWorkflows]}
                loading={tableLoading}
                rowKey={(snapshot) => snapshot.hog_flow_id}
                emptyState={
                    workflowSearchFailed
                        ? "Couldn't search your workflows. Check your connection, then change the search to try again."
                        : searchTerm
                          ? 'No sending workflows match your search.'
                          : 'No workflows have sent email in the last 30 days.'
                }
                columns={[
                    {
                        title: 'Workflow',
                        key: 'workflow',
                        render: (_, snapshot: WorkflowEmailSendingRatesApi) => (
                            <span className="inline-flex flex-wrap items-center gap-2">
                                <Link to={urls.workflow(snapshot.hog_flow_id, 'workflow')} className="font-semibold">
                                    {workflowName(snapshot)}
                                </Link>
                                {/* Without this, a workflow we paused ourselves reads as healthy here,
                                    because the rest of this tab reports the provider's verdict only. */}
                                {snapshot.email_sending_paused && (
                                    <Tooltip
                                        title={`${snapshot.email_sending_paused_reason} Open the workflow to resume sending.`}
                                    >
                                        <LemonTag type="danger" size="small">
                                            Paused
                                        </LemonTag>
                                    </Tooltip>
                                )}
                            </span>
                        ),
                    },
                    {
                        title: 'Bounce rate',
                        key: 'bounce_rate',
                        align: 'right',
                        render: (_, snapshot: WorkflowEmailSendingRatesApi) => (
                            <RateCell rate={snapshot.bounce_rate} kind="bounce" volume={snapshot.emails_sent} />
                        ),
                    },
                    {
                        title: 'Complaint rate',
                        key: 'complaint_rate',
                        align: 'right',
                        render: (_, snapshot: WorkflowEmailSendingRatesApi) => (
                            <RateCell rate={snapshot.complaint_rate} kind="complaint" volume={snapshot.emails_sent} />
                        ),
                    },
                    {
                        title: 'Emails sent',
                        key: 'emails_sent',
                        align: 'right',
                        render: (_, snapshot: WorkflowEmailSendingRatesApi) =>
                            humanFriendlyNumber(snapshot.emails_sent),
                    },
                ]}
            />
        </div>
    )
}
