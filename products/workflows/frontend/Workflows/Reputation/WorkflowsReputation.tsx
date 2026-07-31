import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonTable, Link, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type {
    EmailSendingRatesApi,
    WorkflowEmailSendingRatesApi,
} from 'products/workflows/frontend/generated/api.schemas'

import { workflowsReputationLogic } from './workflowsReputationLogic'

function formatRate(rate: number): string {
    return percentage(rate, 2, true)
}

// Must match the endpoint's window (HogFlowViewSet.REPUTATION_WINDOW_DAYS) and cap
// (HogFlowViewSet.WORKFLOW_REPUTATION_LIMIT).
const WINDOW_TOOLTIP = 'Calculated over your workflow email from the last 30 days.'
const WORKFLOW_LIMIT = 50

function MetricLabel({ label, tooltip }: { label: string; tooltip: string }): JSX.Element {
    return (
        <Tooltip title={tooltip}>
            <div className="text-secondary text-xs border-b border-dotted border-current inline-block cursor-default">
                {label}
            </div>
        </Tooltip>
    )
}

function TeamRatesCard({ reputation }: { reputation: EmailSendingRatesApi }): JSX.Element {
    return (
        <div className="border rounded p-4 bg-surface-primary">
            <h3 className="mb-0">Project email sending health</h3>
            <div className="flex flex-wrap gap-8 mt-3">
                <div>
                    <MetricLabel
                        label="Bounce rate"
                        tooltip={`Hard (permanent) bounces divided by emails sent. Transient bounces like a full mailbox are not counted. ${WINDOW_TOOLTIP}`}
                    />
                    <div className="text-lg font-semibold">{formatRate(reputation.bounce_rate)}</div>
                </div>
                <div>
                    <MetricLabel
                        label="Spam complaint rate"
                        tooltip={`Spam complaints divided by emails sent. ${WINDOW_TOOLTIP}`}
                    />
                    <div className="text-lg font-semibold">{formatRate(reputation.complaint_rate)}</div>
                </div>
                <div>
                    <MetricLabel label="Emails sent (last 30 days)" tooltip={WINDOW_TOOLTIP} />
                    <div className="text-lg font-semibold">{humanFriendlyNumber(reputation.emails_sent)}</div>
                </div>
            </div>
        </div>
    )
}

export function WorkflowsReputation(): JSX.Element {
    const { teamReputation, workflowSnapshots, reputationResponseLoading, search } = useValues(workflowsReputationLogic)
    const { setSearch } = useActions(workflowsReputationLogic)

    return (
        <div className="space-y-4" data-attr="workflows-reputation">
            <LemonBanner type="info" data-attr="workflows-reputation-beta-banner">
                Sending health is shown for transparency: high bounce or spam complaint rates hurt email deliverability.
                Reputation judgment and enforcement are handled per project by our email provider.
            </LemonBanner>
            {teamReputation ? (
                <TeamRatesCard reputation={teamReputation} />
            ) : (
                !reputationResponseLoading && (
                    <div className="border rounded p-4 text-secondary">
                        No email sending data yet. Rates appear here once your workflows send email.
                    </div>
                )
            )}
            <div className="flex items-center gap-3">
                <LemonInput
                    type="search"
                    placeholder="Search workflows"
                    value={search}
                    onChange={setSearch}
                    className="max-w-80"
                    data-attr="workflows-reputation-search"
                />
                {!search.trim() && workflowSnapshots.length >= WORKFLOW_LIMIT && (
                    <span className="text-secondary text-xs">
                        Showing the {WORKFLOW_LIMIT} workflows with the highest rates. Search to find any other sending
                        workflow.
                    </span>
                )}
            </div>
            <LemonTable
                dataSource={[...workflowSnapshots]}
                loading={reputationResponseLoading}
                rowKey={(snapshot) => snapshot.hog_flow_id}
                emptyState={
                    search.trim()
                        ? 'No sending workflows match your search.'
                        : 'No workflows have sent email in the last 30 days.'
                }
                columns={[
                    {
                        title: 'Workflow',
                        key: 'workflow',
                        render: (_, snapshot: WorkflowEmailSendingRatesApi) => (
                            <Link to={urls.workflow(snapshot.hog_flow_id, 'workflow')} className="font-semibold">
                                {snapshot.hog_flow_name || snapshot.hog_flow_id}
                            </Link>
                        ),
                    },
                    {
                        title: 'Bounce rate',
                        key: 'bounce_rate',
                        align: 'right',
                        render: (_, snapshot: WorkflowEmailSendingRatesApi) => formatRate(snapshot.bounce_rate),
                    },
                    {
                        title: 'Complaint rate',
                        key: 'complaint_rate',
                        align: 'right',
                        render: (_, snapshot: WorkflowEmailSendingRatesApi) => formatRate(snapshot.complaint_rate),
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
