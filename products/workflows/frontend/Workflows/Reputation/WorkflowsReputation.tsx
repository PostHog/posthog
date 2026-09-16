import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonTable, LemonTag, LemonTagType, Link, Tooltip } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type {
    AwsTenantReputationApi,
    AwsTenantReputationHealthEnumApi,
    EmailSendingAllowanceApi,
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

// Below this much volume one event on its own clears the elevated line, so a tag would be
// reporting noise: one bounce in 20 sends reads as 5%.
function minimumVolumeToClassify(kind: 'bounce' | 'complaint'): number {
    return Math.ceil(1 / RATE_THRESHOLDS[kind].elevated)
}

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

// AWS returning nothing for a metric is not the same as the metric being zero, and a 0.00% spam
// complaint rate with a green tag is the most misleading thing this table could show. The API names
// the rates it could not load, and those say so instead.
function MissingRate({ reason }: { reason: 'unavailable' | 'no-rate' }): JSX.Element {
    const tooltip =
        reason === 'unavailable'
            ? 'AWS did not return this metric, so there is no number to show. It usually reappears on the next refresh.'
            : 'No complaints could be measured here: either this provider does not report them back to senders, or none of your email to it was delivered. Watch the delivery rate instead.'
    return (
        <Tooltip title={tooltip}>
            <span className="text-secondary cursor-default">
                {reason === 'unavailable' ? "Couldn't load" : 'No data'}
            </span>
        </Tooltip>
    )
}

function RateCell({
    rate,
    kind,
    // What the rate divides by, which differs per kind: sends for bounces, and for complaints the
    // far smaller set of deliveries the provider reports them for.
    volume,
}: {
    rate: number
    kind: 'bounce' | 'complaint'
    volume: number
}): JSX.Element {
    const label = kind === 'bounce' ? 'bounce rate' : 'spam complaint rate'
    const minimumVolume = minimumVolumeToClassify(kind)
    if (volume < minimumVolume) {
        const noun = kind === 'bounce' ? 'emails sent' : 'deliveries this provider reports complaints for'
        return (
            <Tooltip
                title={`Too little volume to judge the ${label}. Under ${humanFriendlyNumber(minimumVolume)} ${noun}, one ${kind === 'bounce' ? 'bounce' : 'complaint'} on its own would put this above ${formatRate(RATE_THRESHOLDS[kind].elevated)}.`}
            >
                <span className="tabular-nums text-secondary cursor-default">{formatRate(rate)}</span>
            </Tooltip>
        )
    }
    const level = classifyRate(rate, kind)
    const tag = RATE_LEVEL_TAG[level]
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

function MetricLabel({
    label,
    tooltip,
    description,
}: {
    label: string
    tooltip: string
    description?: string
}): JSX.Element {
    const labelNode = (
        <Tooltip title={tooltip}>
            <div className="text-secondary text-xs border-b border-dotted border-current inline-block cursor-default">
                {label}
            </div>
        </Tooltip>
    )
    if (!description) {
        return labelNode
    }
    return (
        <div>
            {labelNode}
            <div className="text-secondary text-xs mt-1">{description}</div>
        </div>
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

// SES names providers as one capitalized word, which is not how people write most of them. Only
// the names that read wrong are listed; anything absent is shown as SES reports it, so a provider
// added to SES_ISP_DIMENSIONS still renders without a matching entry here. `__other__` is the
// backend's name for the volume it could not attribute to any of them.
const ISP_DISPLAY_NAMES: Record<string, string> = {
    Aol: 'AOL',
    Gmx: 'GMX',
    Icloud: 'Apple iCloud',
    __other__: 'Other providers',
}

function ispDisplayName(isp: string): string {
    return ISP_DISPLAY_NAMES[isp] ?? isp
}

function IspBreakdown({
    isps,
    sharedDomains,
    emailsSent,
}: {
    isps: readonly IspSendingHealthApi[]
    sharedDomains: readonly string[]
    /** The card's own total, to reconcile against. Null when the project sent no workflow email. */
    emailsSent: number | null
}): JSX.Element | null {
    // The API returns [] unless the flag and access checks pass on its side, so gating on isps alone
    // keeps one decision. A second client flag check can bucket differently and hide returned rows.
    if (isps.length === 0) {
        return null
    }
    return (
        <div className="mt-4 space-y-2" data-attr="workflows-reputation-isp-breakdown">
            <MetricLabel
                label="By mailbox provider"
                description={
                    sharedDomains.length > 0
                        ? `Counts every email sent from ${sharedDomains.join(', ')}, including email from other projects using ${sharedDomains.length > 1 ? 'those domains' : 'that domain'}.`
                        : undefined
                }
                tooltip={`The project-wide rates above pool every provider together, so a struggling provider can be hidden by the others. This table splits the rates out per provider. A provider that accepts your mail and then files it as spam still reads as healthy here. ${WINDOW_TOOLTIP}`}
            />
            <LemonTable
                dataSource={[...isps]}
                rowKey={(row) => row.isp}
                columns={[
                    {
                        title: 'Provider',
                        key: 'isp',
                        render: (_, row: IspSendingHealthApi) =>
                            row.isp === '__other__' ? (
                                <Tooltip title="Mail to providers this table does not list individually.">
                                    <span className="font-semibold cursor-default">{ispDisplayName(row.isp)}</span>
                                </Tooltip>
                            ) : (
                                <span className="font-semibold">{ispDisplayName(row.isp)}</span>
                            ),
                    },
                    {
                        title: 'Delivery rate',
                        key: 'delivery_rate',
                        align: 'right',
                        render: (_, row: IspSendingHealthApi) =>
                            row.delivery_rate === null ? (
                                <MissingRate reason="unavailable" />
                            ) : (
                                <Tooltip title="Emails this provider accepted, divided by emails sent to it. Accepting a message is not the same as putting it in the inbox: a provider can accept your email and still file it as spam.">
                                    <span className="tabular-nums cursor-default">{formatRate(row.delivery_rate)}</span>
                                </Tooltip>
                            ),
                    },
                    {
                        title: 'Hard bounce rate',
                        key: 'bounce_rate',
                        tooltip:
                            'Permanent rejections: the address does not exist, or the provider refused the mail outright.',
                        align: 'right',
                        render: (_, row: IspSendingHealthApi) =>
                            row.bounce_rate === null ? (
                                <MissingRate reason="unavailable" />
                            ) : (
                                <RateCell rate={row.bounce_rate} kind="bounce" volume={row.emails_sent} />
                            ),
                    },
                    {
                        title: 'Soft bounce rate',
                        key: 'transient_bounce_rate',
                        tooltip:
                            'Temporary rejections the provider may accept on a retry, such as a full mailbox, rate limiting, or a provider holding mail from a sender it does not recognize yet. These are why a delivery rate can fall short without any hard bounces.',
                        align: 'right',
                        render: (_, row: IspSendingHealthApi) =>
                            row.transient_bounce_rate === null ? (
                                <MissingRate reason="unavailable" />
                            ) : (
                                <span className="tabular-nums">{formatRate(row.transient_bounce_rate)}</span>
                            ),
                    },
                    {
                        title: 'Complaint rate',
                        key: 'complaint_rate',
                        align: 'right',
                        render: (_, row: IspSendingHealthApi) =>
                            row.complaint_rate === null ? (
                                <MissingRate
                                    reason={row.unavailable?.includes('complaint') ? 'unavailable' : 'no-rate'}
                                />
                            ) : (
                                <RateCell rate={row.complaint_rate} kind="complaint" volume={row.complaint_base} />
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
            {sharedDomains.length === 0 && <IspCoverage isps={isps} emailsSent={emailsSent} />}
        </div>
    )
}

// The card counts every workflow email sent; the table counts what AWS attributed to the verified
// domains. Different populations, and the table is routinely the smaller one.
//
// Only sound while no domain is shared. A shared domain puts another project's mail in the table
// but not in the card, so the two stop being comparable and the caller withholds this.
function IspCoverage({
    isps,
    emailsSent,
}: {
    isps: readonly IspSendingHealthApi[]
    emailsSent: number | null
}): JSX.Element | null {
    const attributed = isps.reduce((total, isp) => total + isp.emails_sent, 0)
    if (emailsSent === null || attributed >= emailsSent) {
        return null
    }
    return (
        <div className="text-secondary text-xs" data-attr="workflows-reputation-isp-coverage">
            Covers {humanFriendlyNumber(attributed)} of the {humanFriendlyNumber(emailsSent)} emails this project sent.
            The rest went out from a domain this breakdown does not cover, or your email provider has not reported on it
            yet.
        </div>
    )
}

function TeamRatesCard({
    reputation,
    aws,
    isps,
    sharedDomains,
    withheldDomains,
}: {
    reputation: EmailSendingRatesApi | null
    aws: AwsTenantReputationApi | null
    isps: readonly IspSendingHealthApi[]
    sharedDomains: readonly string[]
    withheldDomains: readonly string[]
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
            ) : isps.length > 0 ? (
                <div className="text-secondary mt-3">
                    No workflow email in the last 30 days. The breakdown below covers all email sent from your verified
                    domains.
                </div>
            ) : (
                <div className="text-secondary mt-3">
                    No email sending data yet. Rates appear here once your workflows send email.
                </div>
            )}
            {aws && <AwsFindings aws={aws} />}
            <IspBreakdown isps={isps} sharedDomains={sharedDomains} emailsSent={reputation?.emails_sent ?? null} />
            {withheldDomains.length > 0 && (
                <div className="text-secondary text-xs mt-3" data-attr="workflows-reputation-isp-withheld">
                    {withheldDomains.join(', ')} {withheldDomains.length > 1 ? 'are' : 'is'} left out of the provider
                    breakdown. Another project sends from {withheldDomains.length > 1 ? 'them' : 'it'}, and you do not
                    have access to that project.
                </div>
            )}
        </div>
    )
}

function SendingAllowanceCard({ allowance }: { allowance: EmailSendingAllowanceApi }): JSX.Element {
    const hourlyPercent = Math.min(100, (allowance.emails_sent_last_hour / allowance.emails_per_hour) * 100)
    const dailyPercent = Math.min(100, (allowance.emails_sent_last_day / allowance.emails_per_day) * 100)
    return (
        <div className="border rounded p-4 bg-surface-primary" data-attr="workflows-sending-allowance">
            <div className="flex items-center gap-2">
                <h3 className="mb-0">Sending allowance</h3>
                <Tooltip title="Every project shares PostHog's sending infrastructure, so allowances start small and grow with a clean sending record.">
                    <LemonTag type="muted">
                        Tier {allowance.tier} of {allowance.max_tier}
                    </LemonTag>
                </Tooltip>
                {!allowance.enforced && (
                    <Tooltip title="We are measuring what this allowance would do before applying it, so nothing is delayed by it yet.">
                        <LemonTag type="completion">Not applied yet</LemonTag>
                    </Tooltip>
                )}
            </div>
            <p className="text-secondary mt-2 mb-0">
                {allowance.enforced
                    ? 'Your allowance grows as your workflows keep sending with low bounce and spam complaint rates. Emails above the allowance are not dropped, they are sent later.'
                    : 'Your allowance grows as your workflows keep sending with low bounce and spam complaint rates. It is not applied to your sends yet, so these numbers show where you stand rather than a limit you are hitting.'}
            </p>
            <div className="flex flex-wrap gap-8 mt-3">
                <div className="min-w-48">
                    <MetricLabel
                        label="Emails this hour"
                        tooltip="Emails your workflows sent in the last hour, against what this tier allows per hour."
                    />
                    <div className="text-lg font-semibold">
                        {humanFriendlyNumber(allowance.emails_sent_last_hour)} of{' '}
                        {humanFriendlyNumber(allowance.emails_per_hour)}
                    </div>
                    <LemonProgress percent={hourlyPercent} className="mt-1" />
                </div>
                <div className="min-w-48">
                    <MetricLabel
                        label="Emails today"
                        tooltip="Emails your workflows sent in the last 24 hours, against what this tier allows per day."
                    />
                    <div className="text-lg font-semibold">
                        {humanFriendlyNumber(allowance.emails_sent_last_day)} of{' '}
                        {humanFriendlyNumber(allowance.emails_per_day)}
                    </div>
                    <LemonProgress percent={dailyPercent} className="mt-1" />
                </div>
                <div>
                    <MetricLabel
                        label="Largest batch audience"
                        tooltip="The biggest audience this tier allows for a single batch send."
                    />
                    <div className="text-lg font-semibold">{humanFriendlyNumber(allowance.max_batch_audience)}</div>
                </div>
            </div>
        </div>
    )
}

export function WorkflowsReputation(): JSX.Element {
    const {
        awsReputation,
        sendingAllowance,
        teamReputation,
        ispSendingHealth,
        ispSharedDomains,
        ispWithheldDomains,
        workflowSnapshots,
        reputationResponseLoading,
        search,
    } = useValues(workflowsReputationLogic)
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
            {sendingAllowance && <SendingAllowanceCard allowance={sendingAllowance} />}
            {teamReputation || awsReputation || ispSendingHealth.length > 0 || ispWithheldDomains.length > 0 ? (
                <TeamRatesCard
                    reputation={teamReputation}
                    aws={awsReputation}
                    isps={ispSendingHealth}
                    sharedDomains={ispSharedDomains}
                    withheldDomains={ispWithheldDomains}
                />
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
                            <span className="inline-flex items-center gap-2">
                                <Link to={urls.workflow(snapshot.hog_flow_id, 'workflow')} className="font-semibold">
                                    {snapshot.hog_flow_name || snapshot.hog_flow_id}
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
