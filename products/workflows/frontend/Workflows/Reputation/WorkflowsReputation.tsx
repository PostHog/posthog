import { useValues } from 'kea'

import { LemonTable, LemonTag, LemonTagType, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type {
    EmailReputationSnapshotApi,
    EmailReputationStateEnumApi,
    WorkflowEmailReputationSnapshotApi,
} from 'products/workflows/frontend/generated/api.schemas'

import { workflowsReputationLogic } from './workflowsReputationLogic'

// Descriptions must match the evaluator's default thresholds
// (nodejs/src/cdp/services/email-reputation/classifier.ts DEFAULT_THRESHOLDS).
const STATE_CONFIG: Record<EmailReputationStateEnumApi, { label: string; type: LemonTagType; tooltip: string }> = {
    healthy: {
        label: 'Healthy',
        type: 'success',
        tooltip:
            'Hard bounce rate below 2% and spam complaint rate below 0.1%. Transient bounces (greylisting, mailbox full) are not counted.',
    },
    warning: {
        label: 'Warning',
        type: 'warning',
        tooltip:
            'Hard bounce rate at or above 2%, or spam complaint rate at or above 0.1%. Review your recipient list before rates climb further.',
    },
    critical: {
        label: 'Critical',
        type: 'danger',
        tooltip:
            'Hard bounce rate at or above 5%, or spam complaint rate at or above 0.5%. Sending at these rates puts email deliverability at risk.',
    },
    insufficient_data: {
        label: 'Not enough data',
        type: 'muted',
        tooltip: 'Fewer than 100 emails in the evaluated window, which is too few to judge reliably.',
    },
}

function StateTag({ state }: { state: EmailReputationStateEnumApi }): JSX.Element {
    const config = STATE_CONFIG[state] ?? STATE_CONFIG.insufficient_data
    return (
        <Tooltip title={config.tooltip}>
            <LemonTag type={config.type}>{config.label}</LemonTag>
        </Tooltip>
    )
}

function formatRate(rate: number): string {
    return percentage(rate, 2, true)
}

function TeamReputationCard({ reputation }: { reputation: EmailReputationSnapshotApi }): JSX.Element {
    return (
        <div className="border rounded p-4 bg-surface-primary">
            <div className="flex items-center gap-2">
                <h3 className="mb-0">Project email reputation</h3>
                <StateTag state={reputation.state} />
            </div>
            <div className="flex flex-wrap gap-8 mt-3">
                <div>
                    <div className="text-secondary text-xs">Bounce rate</div>
                    <div className="text-lg font-semibold">{formatRate(reputation.bounce_rate)}</div>
                </div>
                <div>
                    <div className="text-secondary text-xs">Spam complaint rate</div>
                    <div className="text-lg font-semibold">{formatRate(reputation.complaint_rate)}</div>
                </div>
                <div>
                    <div className="text-secondary text-xs">Emails evaluated (recent volume)</div>
                    <div className="text-lg font-semibold">{humanFriendlyNumber(reputation.emails_sent)}</div>
                </div>
                <div>
                    <div className="text-secondary text-xs">Last evaluated</div>
                    <div className="text-lg font-semibold">
                        <TZLabel time={reputation.evaluated_at} />
                    </div>
                </div>
            </div>
        </div>
    )
}

function WorkflowHistoryTable({ history }: { history: readonly EmailReputationSnapshotApi[] }): JSX.Element {
    return (
        <div className="py-1">
            <div className="text-secondary text-xs mb-1">Daily scores from the last 7 days</div>
            <LemonTable
                size="small"
                embedded
                dataSource={[...history].reverse()}
                rowKey={(snapshot) => snapshot.evaluated_at}
                columns={[
                    {
                        title: 'Evaluated',
                        key: 'evaluated_at',
                        render: (_, snapshot: EmailReputationSnapshotApi) => <TZLabel time={snapshot.evaluated_at} />,
                    },
                    {
                        title: 'State',
                        key: 'state',
                        render: (_, snapshot: EmailReputationSnapshotApi) => <StateTag state={snapshot.state} />,
                    },
                    {
                        title: 'Bounce rate',
                        key: 'bounce_rate',
                        align: 'right',
                        render: (_, snapshot: EmailReputationSnapshotApi) => formatRate(snapshot.bounce_rate),
                    },
                    {
                        title: 'Complaint rate',
                        key: 'complaint_rate',
                        align: 'right',
                        render: (_, snapshot: EmailReputationSnapshotApi) => formatRate(snapshot.complaint_rate),
                    },
                    {
                        title: 'Emails sent',
                        key: 'emails_sent',
                        align: 'right',
                        render: (_, snapshot: EmailReputationSnapshotApi) => humanFriendlyNumber(snapshot.emails_sent),
                    },
                ]}
            />
        </div>
    )
}

export function WorkflowsReputation(): JSX.Element {
    const { teamReputation, workflowSnapshots, reputationResponseLoading } = useValues(workflowsReputationLogic)

    return (
        <div className="space-y-4" data-attr="workflows-reputation">
            {teamReputation ? (
                <TeamReputationCard reputation={teamReputation} />
            ) : (
                !reputationResponseLoading && (
                    <div className="border rounded p-4 text-secondary">
                        No reputation data yet. Reputation is calculated daily from email bounces and spam complaints
                        once your workflows start sending email.
                    </div>
                )
            )}
            <LemonTable
                dataSource={[...workflowSnapshots]}
                loading={reputationResponseLoading}
                rowKey={(snapshot) => snapshot.hog_flow_id}
                emptyState="No workflows have sent enough email to be evaluated yet."
                columns={[
                    {
                        title: 'Workflow',
                        key: 'workflow',
                        render: (_, snapshot: WorkflowEmailReputationSnapshotApi) => (
                            <Link to={urls.workflow(snapshot.hog_flow_id, 'workflow')} className="font-semibold">
                                {snapshot.hog_flow_name || snapshot.hog_flow_id}
                            </Link>
                        ),
                    },
                    {
                        title: 'State',
                        key: 'state',
                        render: (_, snapshot: WorkflowEmailReputationSnapshotApi) => (
                            <StateTag state={snapshot.state} />
                        ),
                    },
                    {
                        title: 'Bounce rate',
                        key: 'bounce_rate',
                        align: 'right',
                        render: (_, snapshot: WorkflowEmailReputationSnapshotApi) => formatRate(snapshot.bounce_rate),
                    },
                    {
                        title: 'Complaint rate',
                        key: 'complaint_rate',
                        align: 'right',
                        render: (_, snapshot: WorkflowEmailReputationSnapshotApi) =>
                            formatRate(snapshot.complaint_rate),
                    },
                    {
                        title: 'Emails sent',
                        key: 'emails_sent',
                        align: 'right',
                        render: (_, snapshot: WorkflowEmailReputationSnapshotApi) =>
                            humanFriendlyNumber(snapshot.emails_sent),
                    },
                    {
                        title: 'Evaluated',
                        key: 'evaluated_at',
                        render: (_, snapshot: WorkflowEmailReputationSnapshotApi) => (
                            <TZLabel time={snapshot.evaluated_at} />
                        ),
                    },
                ]}
                expandable={{
                    rowExpandable: (snapshot: WorkflowEmailReputationSnapshotApi) => snapshot.history.length > 1,
                    expandedRowRender: (snapshot: WorkflowEmailReputationSnapshotApi) => (
                        <WorkflowHistoryTable history={snapshot.history} />
                    ),
                }}
            />
        </div>
    )
}
