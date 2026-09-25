import { useValues } from 'kea'

import { LemonTable, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { IspSendingHealthApi } from 'products/workflows/frontend/generated/api.schemas'

import { RateCell } from './RateCell'
import { OTHER_ISP, WINDOW_TOOLTIP, formatRate, ispDisplayName } from './reputationUtils'
import { workflowsReputationLogic } from './workflowsReputationLogic'

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

// The strip counts every workflow email sent; the table counts what AWS attributed to the verified
// domains. Different populations, and the table is routinely the smaller one.
//
// Only sound while no domain is shared. A shared domain puts another project's mail in the table
// but not in the strip, so the two stop being comparable and the caller withholds this.
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

export function ReputationProviderBreakdown(): JSX.Element {
    const { ispSendingHealth, ispSharedDomains, ispWithheldDomains, teamReputation } =
        useValues(workflowsReputationLogic)

    return (
        <div className="space-y-2" data-attr="workflows-reputation-isp-breakdown">
            {/* The API returns [] unless the flag and access checks pass on its side, so gating on
                the rows alone keeps one decision. A second client flag check can bucket
                differently and hide returned rows. */}
            {ispSendingHealth.length > 0 && (
                <>
                    <p className="text-secondary mb-0">
                        The project rates pool every provider together, so one struggling provider can hide behind the
                        others. A provider that accepts your email and then files it as spam still reads as healthy
                        here. {WINDOW_TOOLTIP}
                        {ispSharedDomains.length > 0 &&
                            ` Counts every email sent from ${ispSharedDomains.join(', ')}, including email from other projects using ${ispSharedDomains.length > 1 ? 'those domains' : 'that domain'}.`}
                    </p>
                    <LemonTable
                        dataSource={[...ispSendingHealth]}
                        rowKey={(row) => row.isp}
                        columns={[
                            {
                                title: 'Provider',
                                key: 'isp',
                                render: (_, row: IspSendingHealthApi) =>
                                    row.isp === OTHER_ISP ? (
                                        <Tooltip title="Mail to providers this table does not list individually.">
                                            <span className="font-semibold cursor-default">
                                                {ispDisplayName(row.isp)}
                                            </span>
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
                                            <span className="tabular-nums cursor-default">
                                                {formatRate(row.delivery_rate)}
                                            </span>
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
                                        <RateCell
                                            rate={row.complaint_rate}
                                            kind="complaint"
                                            volume={row.complaint_base}
                                        />
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
                    {ispSharedDomains.length === 0 && (
                        <IspCoverage isps={ispSendingHealth} emailsSent={teamReputation?.emails_sent ?? null} />
                    )}
                </>
            )}
            {ispWithheldDomains.length > 0 && (
                <div className="text-secondary text-xs" data-attr="workflows-reputation-isp-withheld">
                    {ispWithheldDomains.join(', ')} {ispWithheldDomains.length > 1 ? 'are' : 'is'} left out of the
                    provider breakdown. Another project sends from {ispWithheldDomains.length > 1 ? 'them' : 'it'}, and
                    you do not have access to that project.
                </div>
            )}
        </div>
    )
}
