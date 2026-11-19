import { useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { AwsTenantReputationHealthEnumApi } from 'products/workflows/frontend/generated/api.schemas'

import { reputationResponseLogic } from './reputationResponseLogic'
import { REPUTATION_DOCS_URL, WINDOW_TOOLTIP, formatRate } from './reputationUtils'

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

export function ReputationStatusStrip(): JSX.Element {
    const { awsReputation, teamReputation, ispSendingHealth, emailSendingSuspended } =
        useValues(reputationResponseLogic)

    return (
        <LemonCard
            hoverEffect={false}
            className="px-4 py-2 flex flex-wrap items-center gap-x-6 gap-y-2"
            data-attr="workflows-reputation-status"
        >
            {emailSendingSuspended && (
                <Tooltip title="PostHog suspended email sending for this project. No workflow email goes out until the suspension ends.">
                    <span tabIndex={0} className="inline-flex">
                        <LemonTag type="danger" data-attr="workflows-reputation-suspended-tag">
                            Suspended by PostHog
                        </LemonTag>
                    </span>
                </Tooltip>
            )}
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
                        label="Bounce rate (30 days)"
                        tooltip={`Hard (permanent) bounces divided by emails sent. Transient bounces like a full mailbox are not counted. ${WINDOW_TOOLTIP}`}
                        value={formatRate(teamReputation.bounce_rate)}
                    />
                    <StripStat
                        label="Spam complaint rate (30 days)"
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
        </LemonCard>
    )
}
