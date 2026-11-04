import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import type { TransactionalEmailLogDetailApi } from 'products/messaging/frontend/generated/api.schemas'

import { EMAIL_STATUS_DESCRIPTION, EMAIL_STATUS_LABEL, EMAIL_STATUS_TAG } from './emailLogStatus'

function DetailRow({
    label,
    stacked = false,
    children,
}: {
    label: string
    /** Puts the value under the label, for long values such as IDs. */
    stacked?: boolean
    children: React.ReactNode
}): JSX.Element {
    return (
        <div
            className={
                stacked ? 'flex flex-col gap-0.5 text-sm' : 'flex justify-between items-baseline gap-4 text-sm min-w-0'
            }
        >
            <dt className="text-secondary shrink-0">{label}</dt>
            <dd className={stacked ? 'm-0' : 'm-0 min-w-0 text-right truncate'}>{children}</dd>
        </div>
    )
}

export function TransactionalEmailDetails({ email }: { email: TransactionalEmailLogDetailApi }): JSX.Element {
    return (
        <section className="border rounded bg-surface-primary p-4 flex flex-col gap-3">
            <h3 className="text-sm font-semibold m-0">Details</h3>
            <dl className="flex flex-col gap-2 m-0">
                <DetailRow label="Status">
                    <Tooltip title={EMAIL_STATUS_DESCRIPTION[email.status]}>
                        <LemonTag type={EMAIL_STATUS_TAG[email.status]}>{EMAIL_STATUS_LABEL[email.status]}</LemonTag>
                    </Tooltip>
                </DetailRow>
                <DetailRow label="Email">
                    {email.template_id ? (
                        <Link to={urls.transactionalTemplate(email.template_id)}>
                            {email.template_name || 'Unnamed email'}
                        </Link>
                    ) : (
                        <span className="text-secondary">Deleted email</span>
                    )}
                </DetailRow>
                <DetailRow label="Queued">
                    <TZLabel time={email.created_at} />
                </DetailRow>
                {email.sending_domain && <DetailRow label="Sending domain">{email.sending_domain}</DetailRow>}
                {email.distinct_id && (
                    <DetailRow label="Distinct ID" stacked>
                        <span className="ph-no-capture">
                            <CopyToClipboardInline
                                description="distinct ID"
                                explicitValue={email.distinct_id}
                                iconSize="xsmall"
                            >
                                <span className="font-mono text-xs">{email.distinct_id}</span>
                            </CopyToClipboardInline>
                        </span>
                    </DetailRow>
                )}
                <DetailRow label="Message ID" stacked>
                    <CopyToClipboardInline description="message ID" explicitValue={email.message_id} iconSize="xsmall">
                        <span className="font-mono text-xs">{email.message_id}</span>
                    </CopyToClipboardInline>
                </DetailRow>
            </dl>
        </section>
    )
}
