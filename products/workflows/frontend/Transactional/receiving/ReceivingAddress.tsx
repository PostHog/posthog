import { useActions } from 'kea'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

import { inboundEmailDomainsLogic } from './inboundEmailDomainsLogic'

/** A receiving address. Any name works in front of the @, so the name part is shown as a placeholder. */
export function ReceivingAddress({ domain }: { domain: string }): JSX.Element {
    const { addressCopied } = useActions(inboundEmailDomainsLogic)
    return (
        <span
            className="inline-flex items-center gap-1 font-mono text-sm break-all"
            onClick={() => addressCopied()}
            data-attr="received-email-address"
        >
            <CopyToClipboardInline explicitValue={`hello@${domain}`} description="receiving address" selectable>
                <span>
                    <span className="text-secondary">anything</span>@{domain}
                </span>
            </CopyToClipboardInline>
        </span>
    )
}
