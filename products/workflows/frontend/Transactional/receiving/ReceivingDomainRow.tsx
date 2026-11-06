import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonTag } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { TZLabel } from 'lib/components/TZLabel'

import type { InboundDomainApi, InboundDomainCheckApi } from 'products/workflows/frontend/generated/api.schemas'

import { inboundEmailDomainsLogic } from './inboundEmailDomainsLogic'
import { ReceivingAddress } from './ReceivingAddress'

const CHECK_POLL_MS = 15000

function checkMessage(check: InboundDomainCheckApi | undefined, mxHost: string): string | null {
    switch (check?.state) {
        case 'missing':
            return "We can't see this record yet. DNS changes can take a few minutes to show up."
        case 'conflict':
            return check.found.some((record) => record.endsWith(mxHost))
                ? `Another MX record has the same or a lower priority number, so it gets the mail first: ${check.found.join(', ')}. Remove it, or give our record the lowest number.`
                : `This domain's mail goes elsewhere: ${check.found.join(', ')}. Replace those records with the one above.`
        case 'taken':
            return 'Another project already receives mail on this domain.'
        case 'no_sending_domain':
            return 'This project has no verified sending domain that covers this domain. Verify one, then check again.'
        case 'lookup_failed':
            return "DNS didn't answer. We'll try again."
        default:
            return null
    }
}

export function ReceivingDomainRow({ domain }: { domain: InboundDomainApi }): JSX.Element {
    const { overview, checks, checksLoading } = useValues(inboundEmailDomainsLogic)
    const { checkDomain, removeDomain } = useActions(inboundEmailDomainsLogic)
    const pending = domain.status === 'pending'
    const check = checks[domain.id]
    const mxHost = overview?.mx_host ?? ''
    const message = checkMessage(check, mxHost)

    useEffect(() => {
        if (!pending) {
            return
        }
        const interval = setInterval(() => checkDomain({ id: domain.id }), CHECK_POLL_MS)
        return () => clearInterval(interval)
    }, [pending, domain.id, checkDomain])

    return (
        <div className="border rounded p-3 flex flex-col gap-2" data-attr="received-email-domain-row">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0 flex-wrap">
                    <span className="font-semibold break-all">{domain.domain}</span>
                    <LemonTag type={pending ? 'warning' : 'success'}>
                        {pending ? 'Waiting for DNS' : 'Receiving'}
                    </LemonTag>
                </div>
                <LemonButton
                    size="xsmall"
                    icon={<IconTrash />}
                    status="danger"
                    tooltip="Remove domain"
                    aria-label={`Remove ${domain.domain}`}
                    onClick={() =>
                        LemonDialog.open({
                            title: `Remove ${domain.domain}?`,
                            description:
                                "Mail to this domain will be dropped. Email you've already received stays until it expires.",
                            primaryButton: {
                                children: 'Remove',
                                status: 'danger',
                                onClick: () => removeDomain(domain),
                            },
                            secondaryButton: { children: 'Cancel' },
                        })
                    }
                />
            </div>
            {pending ? (
                <>
                    <p className="m-0 text-sm text-secondary">Add this record at your DNS provider:</p>
                    <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm items-baseline">
                        <span className="text-secondary">Type</span>
                        <span className="font-mono">MX</span>
                        <span className="text-secondary">Name</span>
                        <CopyToClipboardInline description="record name" selectable className="font-mono break-all">
                            {domain.domain}
                        </CopyToClipboardInline>
                        <span className="text-secondary">Priority</span>
                        <span className="font-mono">{overview?.mx_priority}</span>
                        <span className="text-secondary">Value</span>
                        <CopyToClipboardInline description="record value" selectable className="font-mono break-all">
                            {mxHost}
                        </CopyToClipboardInline>
                    </div>
                    {message && <LemonBanner type="warning">{message}</LemonBanner>}
                    <div className="flex flex-wrap items-center gap-3">
                        <LemonButton
                            type="secondary"
                            size="small"
                            loading={checksLoading}
                            onClick={() => checkDomain({ id: domain.id })}
                            data-attr="received-email-check-domain"
                        >
                            Check now
                        </LemonButton>
                        <span className="text-xs text-secondary">
                            {domain.mx_checked_at ? (
                                <>
                                    Last checked <TZLabel time={domain.mx_checked_at} />.{' '}
                                </>
                            ) : null}
                            We keep checking while this is open.
                        </span>
                    </div>
                </>
            ) : (
                <ReceivingAddress domain={domain.domain} />
            )}
        </div>
    )
}
