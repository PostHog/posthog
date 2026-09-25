import { useValues } from 'kea'

import { IconExternal, IconInfo } from '@posthog/icons'
import { LemonButton, LemonTag, LemonTagType, Link, Tooltip } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { AwsTenantReputationHealthEnumApi } from 'products/workflows/frontend/generated/api.schemas'

import { REPUTATION_DOCS_URL, SENDING_TIERS_DOCS_URL, WINDOW_TOOLTIP, formatRate } from './reputationUtils'
import { workflowsReputationLogic } from './workflowsReputationLogic'

const HEALTH_TAG: Record<AwsTenantReputationHealthEnumApi, { label: string; type: LemonTagType }> = {
    healthy: { label: 'Healthy', type: 'success' },
    warning: { label: 'Warning', type: 'warning' },
    critical: { label: 'Critical', type: 'danger' },
    suspended: { label: 'Suspended', type: 'danger' },
}

function StripStat({ label, tooltip, value }: { label: string; tooltip: string; value: string }): JSX.Element {
    return (
        <span className="inline-flex items-baseline gap-1.5">
            <Tooltip title={tooltip}>
                {/* Focusable so the tooltip also opens from the keyboard. */}
                <span tabIndex={0} className="text-secondary border-b border-dotted border-current cursor-default">
                    {label}
                </span>
            </Tooltip>
            <span className="font-semibold tabular-nums">{value}</span>
        </span>
    )
}

function AllowanceUsage({ label, used, cap }: { label: string; used: number; cap: number }): JSX.Element {
    return (
        <span className="inline-flex items-center gap-2 text-xs">
            {/* LemonProgress sets w-full on itself, so the width lives on a wrapper. */}
            <span className="w-16 shrink-0" aria-hidden>
                <LemonProgress percent={(used / cap) * 100} />
            </span>
            <span className="tabular-nums text-secondary whitespace-nowrap">
                {`${humanFriendlyNumber(used)} of ${humanFriendlyNumber(cap)} ${label}`}
            </span>
        </span>
    )
}

export function ReputationStatusStrip(): JSX.Element {
    const { awsReputation, teamReputation, sendingAllowance, ispSendingHealth } = useValues(workflowsReputationLogic)

    return (
        <div
            className="border rounded bg-surface-primary px-4 py-2 flex flex-wrap items-center gap-x-6 gap-y-2"
            data-attr="workflows-reputation-status"
        >
            {awsReputation && (
                <Tooltip title="Your email provider's verdict for this project, based on real mailbox feedback.">
                    <span tabIndex={0} className="inline-flex">
                        <LemonTag
                            type={HEALTH_TAG[awsReputation.health].type}
                            data-attr="workflows-reputation-health-tag"
                        >
                            {HEALTH_TAG[awsReputation.health].label}
                        </LemonTag>
                    </span>
                </Tooltip>
            )}
            {teamReputation ? (
                <>
                    <StripStat
                        label="Bounce rate"
                        tooltip={`Hard (permanent) bounces divided by emails sent. Transient bounces like a full mailbox are not counted. ${WINDOW_TOOLTIP}`}
                        value={formatRate(teamReputation.bounce_rate)}
                    />
                    <StripStat
                        label="Spam complaint rate"
                        tooltip={`Spam complaints divided by emails sent. ${WINDOW_TOOLTIP}`}
                        value={formatRate(teamReputation.complaint_rate)}
                    />
                    <StripStat
                        label="Emails sent (30 days)"
                        tooltip={WINDOW_TOOLTIP}
                        value={humanFriendlyNumber(teamReputation.emails_sent)}
                    />
                </>
            ) : (
                <span className="text-secondary">
                    {ispSendingHealth.length > 0
                        ? 'No workflow email in the last 30 days. The mailbox provider breakdown covers all email sent from your verified domains.'
                        : 'No workflow email in the last 30 days.'}
                </span>
            )}
            <LemonButton
                size="xsmall"
                icon={<IconInfo />}
                to={REPUTATION_DOCS_URL}
                targetBlank
                tooltip="Reputation is judged and enforced per project, from the bounce and spam complaint rates of all its workflow email. Open the guide to see how it works."
                aria-label="How sending reputation works"
                data-attr="workflows-reputation-docs-info"
            />
            {sendingAllowance?.enforced && (
                <div
                    className="flex flex-wrap items-center gap-x-3 gap-y-1 ml-auto"
                    data-attr="workflows-sending-allowance"
                >
                    <Tooltip
                        title={`Your sending allowance grows while your workflows keep bounce and spam complaint rates low. Email over the allowance is sent later, not dropped. This tier allows batch sends of up to ${humanFriendlyNumber(sendingAllowance.max_batch_audience)} recipients.`}
                    >
                        <Link
                            to={SENDING_TIERS_DOCS_URL}
                            target="_blank"
                            className="inline-flex items-center gap-1 text-sm"
                            data-attr="workflows-reputation-tier-docs-link"
                        >
                            <span>{`Tier ${sendingAllowance.tier} of ${sendingAllowance.max_tier}`}</span>
                            <IconExternal />
                        </Link>
                    </Tooltip>
                    <AllowanceUsage
                        label="this hour"
                        used={sendingAllowance.emails_sent_last_hour}
                        cap={sendingAllowance.emails_per_hour}
                    />
                    <AllowanceUsage
                        label="today"
                        used={sendingAllowance.emails_sent_last_day}
                        cap={sendingAllowance.emails_per_day}
                    />
                </div>
            )}
        </div>
    )
}
