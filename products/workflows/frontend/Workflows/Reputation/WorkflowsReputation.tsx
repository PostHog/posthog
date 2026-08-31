import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonTable, LemonTag, LemonTagType, Link, Tooltip } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type {
    AwsTenantReputationApi,
    AwsTenantReputationHealthEnumApi,
    EmailSendingRatesApi,
    IspSendingHealthApi,
    WorkflowEmailSendingRatesApi,
} from 'products/workflows/frontend/generated/api.schemas'

import { workflowsReputationLogic } from './workflowsReputationLogic'

function formatRate(rate: number): string {
    return percentage(rate, 2, true)
}

const HEALTH_TAG: Record<AwsTenantReputationHealthEnumApi, { label: string; type: LemonTagType }> = {
    healthy: { label: 'Healthy', type: 'success' },
    warning: { label: 'Warning', type: 'warning' },
    critical: { label: 'Critical', type: 'danger' },
    suspended: { label: 'Suspended', type: 'danger' },
}

// Per-workflow rate classification. Reserved words like "Warning" / "Critical" belong to the
// tenant-level AWS verdict (HEALTH_TAG above) — these coarser buckets are just a triage aid for
// spotting which workflows are pulling the project's numbers in the wrong direction.
//
// Thresholds mirror SES's account-level reputation dashboard warning lines (bounce: 5% review /
// 10% pause; complaint: 0.1% review / 0.5% pause), deliberately conservative early warnings.
// Actual tenant enforcement (the Standard reputation policy) pauses much higher — high-severity
// findings at >15% bounce / >1% complaint — so a "high" rate here means "fix this now", not
// "sending is about to stop". Sources:
// https://docs.aws.amazon.com/ses/latest/dg/reputationdashboardmessages.html (dashboard lines)
// https://aws.amazon.com/blogs/messaging-and-targeting/implement-tenants-in-your-amazon-ses-environment-part-3-implementation-guide/ (tenant policy lines)
const RATE_THRESHOLDS = {
    bounce: { elevated: 0.03, high: 0.05 },
    complaint: { elevated: 0.001, high: 0.005 },
} as const

type RateLevel = 'healthy' | 'elevated' | 'high'

function classifyRate(rate: number, kind: 'bounce' | 'complaint'): RateLevel {
    const thresholds = RATE_THRESHOLDS[kind]
    if (rate >= thresholds.high) {
        return 'high'
    }
    if (rate >= thresholds.elevated) {
        return 'elevated'
    }
    return 'healthy'
}

const RATE_LEVEL_TAG: Record<RateLevel, { label: string; type: LemonTagType }> = {
    healthy: { label: 'Healthy', type: 'success' },
    elevated: { label: 'Elevated', type: 'warning' },
    high: { label: 'High', type: 'danger' },
}

function RateCell({ rate, kind }: { rate: number; kind: 'bounce' | 'complaint' }): JSX.Element {
    const level = classifyRate(rate, kind)
    const tag = RATE_LEVEL_TAG[level]
    const label = kind === 'bounce' ? 'bounce rate' : 'spam complaint rate'
    const highPct = formatRate(RATE_THRESHOLDS[kind].high)
    const elevatedPct = formatRate(RATE_THRESHOLDS[kind].elevated)
    const tooltip =
        level === 'high'
            ? `Above ${highPct} ${label}. This damages deliverability and, if it keeps climbing, sending for this project can be paused.`
            : level === 'elevated'
              ? `Above ${elevatedPct} ${label}. Worth investigating before it reaches ${highPct}.`
              : `Below ${elevatedPct} ${label}.`
    return (
        <Tooltip title={tooltip}>
            <span className="inline-flex items-center gap-2 cursor-default justify-end">
                <LemonTag type={tag.type} size="small">
                    {tag.label}
                </LemonTag>
                <span className="tabular-nums">{formatRate(rate)}</span>
            </span>
        </Tooltip>
    )
}

const FINDING_TYPE_LABELS: Record<string, string> = {
    DKIM: 'DKIM setup',
    DMARC: 'DMARC setup',
    SPF: 'SPF setup',
    BIMI: 'BIMI setup',
    COMPLAINT: 'Spam complaints',
    BOUNCE: 'Bounces',
    FEEDBACK_3P: 'Third-party feedback',
    IP_LISTING: 'Blocklist listing',
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

function AwsFindings({ aws }: { aws: AwsTenantReputationApi }): JSX.Element | null {
    if (aws.findings.length === 0) {
        return null
    }
    return (
        <div className="mt-4 space-y-2" data-attr="workflows-reputation-aws-findings">
            <div className="text-secondary text-xs font-semibold uppercase">Sending health findings</div>
            {aws.findings.map((finding, index) => (
                <div key={index} className="border rounded p-3 flex gap-3 items-start">
                    <LemonTag type={finding.impact === 'HIGH' ? 'danger' : 'warning'}>
                        {finding.impact === 'HIGH' ? 'High impact' : 'Low impact'}
                    </LemonTag>
                    <div>
                        <div className="font-semibold">
                            {FINDING_TYPE_LABELS[finding.finding_type] ?? finding.finding_type}
                        </div>
                        {finding.description && <div className="text-secondary">{finding.description}</div>}
                    </div>
                </div>
            ))}
        </div>
    )
}

// A single point is a reading, not a trend, so the column stays empty until there are two.
const MIN_TREND_POINTS = 2

function DeliveryTrend({ isp }: { isp: IspSendingHealthApi }): JSX.Element | null {
    if (isp.daily.length < MIN_TREND_POINTS) {
        return null
    }
    return (
        <Sparkline
            data={isp.daily.map((point) => point.delivery_rate * 100)}
            labels={isp.daily.map((point) => point.date)}
            name={`${isp.isp} delivery rate (%)`}
            type="line"
            renderTooltipValue={(value) => `${value.toFixed(1)}%`}
            // Fixed 0-100 rather than auto-scaled per row: these are read against each other, and
            // an auto-scaled axis draws a steady 40% provider identically to a steady 98% one.
            valueDomain={{ min: 0, max: 100 }}
            // Sizes Sparkline's own container: without a height it grows to fill the table cell
            // and the chart bleeds across rows.
            className="h-8 w-28"
        />
    )
}

function IspBreakdown({ isps }: { isps: readonly IspSendingHealthApi[] }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.WORKFLOWS_ISP_SENDING_HEALTH] || isps.length === 0) {
        return null
    }
    return (
        <div className="mt-4 space-y-2" data-attr="workflows-reputation-isp-breakdown">
            <MetricLabel
                label="By mailbox provider"
                tooltip={`One provider filtering your email is invisible in the project-wide rates above, which pool every provider together. ${WINDOW_TOOLTIP}`}
            />
            <LemonTable
                dataSource={[...isps]}
                rowKey={(row) => row.isp}
                columns={[
                    {
                        title: 'Provider',
                        key: 'isp',
                        render: (_, row: IspSendingHealthApi) => <span className="font-semibold">{row.isp}</span>,
                    },
                    {
                        title: 'Delivery rate',
                        key: 'delivery_rate',
                        align: 'right',
                        render: (_, row: IspSendingHealthApi) => (
                            <Tooltip title="Emails this provider accepted, divided by emails sent to it. Accepting a message is not the same as putting it in the inbox: a provider can accept your email and still file it as spam.">
                                <span className="tabular-nums cursor-default">{formatRate(row.delivery_rate)}</span>
                            </Tooltip>
                        ),
                    },
                    {
                        title: 'Delivery trend',
                        key: 'delivery_trend',
                        tooltip: 'Every provider is drawn on the same 0-100% axis, so rows can be compared by height.',
                        render: (_, row: IspSendingHealthApi) => <DeliveryTrend isp={row} />,
                    },
                    {
                        title: 'Bounce rate',
                        key: 'bounce_rate',
                        align: 'right',
                        render: (_, row: IspSendingHealthApi) => <RateCell rate={row.bounce_rate} kind="bounce" />,
                    },
                    {
                        title: 'Complaint rate',
                        key: 'complaint_rate',
                        align: 'right',
                        render: (_, row: IspSendingHealthApi) =>
                            row.complaint_rate === null ? (
                                <Tooltip title="This provider does not report spam complaints back to senders, so there is no rate to show. Watch its delivery rate instead.">
                                    <span className="text-secondary cursor-default">Not reported</span>
                                </Tooltip>
                            ) : (
                                <RateCell rate={row.complaint_rate} kind="complaint" />
                            ),
                    },
                    {
                        title: 'Emails sent',
                        key: 'emails_sent',
                        align: 'right',
                        render: (_, row: IspSendingHealthApi) => humanFriendlyNumber(row.emails_sent),
                    },
                ]}
            />
        </div>
    )
}

function TeamRatesCard({
    reputation,
    aws,
    isps,
}: {
    reputation: EmailSendingRatesApi | null
    aws: AwsTenantReputationApi | null
    isps: readonly IspSendingHealthApi[]
}): JSX.Element {
    return (
        <div className="border rounded p-4 bg-surface-primary">
            <div className="flex items-center gap-2">
                <h3 className="mb-0">Project email sending health</h3>
                {aws && (
                    <Tooltip title="Based on real mailbox feedback across all of this project's workflow email.">
                        <LemonTag type={HEALTH_TAG[aws.health].type} data-attr="workflows-reputation-health-tag">
                            {HEALTH_TAG[aws.health].label}
                        </LemonTag>
                    </Tooltip>
                )}
            </div>
            {reputation ? (
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
            ) : (
                <div className="text-secondary mt-3">
                    No email sending data yet. Rates appear here once your workflows send email.
                </div>
            )}
            {aws && <AwsFindings aws={aws} />}
            <IspBreakdown isps={isps} />
        </div>
    )
}

export function WorkflowsReputation(): JSX.Element {
    const { awsReputation, teamReputation, ispSendingHealth, workflowSnapshots, reputationResponseLoading, search } =
        useValues(workflowsReputationLogic)
    const { setSearch } = useActions(workflowsReputationLogic)

    return (
        <div className="space-y-4" data-attr="workflows-reputation">
            {awsReputation?.sending_status === 'DISABLED' && (
                <LemonBanner type="error" data-attr="workflows-reputation-disabled-banner">
                    {awsReputation.findings.length > 0
                        ? 'Email sending is paused for this project because of reputation problems. Fix the open findings below, then contact support to get sending re-enabled.'
                        : 'Email sending is paused for this project. Contact support to get sending re-enabled.'}
                </LemonBanner>
            )}
            <LemonBanner type="info" data-attr="workflows-reputation-beta-banner">
                Sending health is shown for transparency: high bounce or spam complaint rates hurt email deliverability.
                We judge and enforce reputation per project.
            </LemonBanner>
            {teamReputation || awsReputation ? (
                <TeamRatesCard reputation={teamReputation} aws={awsReputation} isps={ispSendingHealth} />
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
                        render: (_, snapshot: WorkflowEmailSendingRatesApi) => (
                            <RateCell rate={snapshot.bounce_rate} kind="bounce" />
                        ),
                    },
                    {
                        title: 'Complaint rate',
                        key: 'complaint_rate',
                        align: 'right',
                        render: (_, snapshot: WorkflowEmailSendingRatesApi) => (
                            <RateCell rate={snapshot.complaint_rate} kind="complaint" />
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
