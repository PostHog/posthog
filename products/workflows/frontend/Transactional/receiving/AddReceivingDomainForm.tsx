import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCheckbox, LemonInput, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { inboundEmailDomainsLogic } from './inboundEmailDomainsLogic'

export function AddReceivingDomainForm(): JSX.Element {
    const { overview, hostname, formError, preflightLoading, addedDomainLoading, generatedDomain } =
        useValues(inboundEmailDomainsLogic)
    const { setHostname, runPreflight, openDomains } = useActions(inboundEmailDomainsLogic)
    const verified = overview?.verified_sending_domains ?? []
    const suggestion = verified[0] ? `${overview?.default_subdomain}.${verified[0]}` : `inbound.yourcompany.com`
    const busy = preflightLoading || addedDomainLoading

    if (verified.length === 0) {
        return (
            <div className="flex flex-col gap-3" data-attr="received-email-no-verified-domain">
                <p className="m-0">
                    Your own domain has to be verified for sending first, so we know it's yours. You can do that under{' '}
                    <Link to={urls.transactional('channels')}>Messaging</Link>.
                </p>
                {generatedDomain && (
                    <p className="m-0 text-secondary">
                        Until then, your ready-made address already works, and you can forward existing mail to it.
                    </p>
                )}
            </div>
        )
    }

    return (
        <form
            className="flex flex-col gap-3"
            onSubmit={(event) => {
                event.preventDefault()
                if (!busy && hostname.trim()) {
                    runPreflight()
                }
            }}
        >
            <div className="flex flex-col gap-1">
                <label className="font-semibold text-sm" htmlFor="received-email-domain-input">
                    Domain
                </label>
                <LemonInput
                    id="received-email-domain-input"
                    autoFocus
                    value={hostname}
                    onChange={setHostname}
                    placeholder={suggestion}
                    data-attr="received-email-domain-input"
                />
                <p className="m-0 text-xs text-secondary">
                    Use a subdomain of {verified.join(', ')}. Mail for a subdomain doesn't affect your other addresses.
                    We suggest {suggestion}.
                </p>
            </div>
            {formError && (
                <LemonBanner type="error" data-attr="received-email-domain-error">
                    {formError}
                </LemonBanner>
            )}
            <div className="flex justify-end gap-2">
                <LemonButton onClick={() => openDomains()}>Back</LemonButton>
                <LemonButton
                    type="primary"
                    htmlType="submit"
                    loading={busy}
                    disabledReason={!hostname.trim() ? 'Enter a domain' : undefined}
                    data-attr="received-email-domain-continue"
                >
                    Continue
                </LemonButton>
            </div>
        </form>
    )
}

export function ConfirmMoveMail(): JSX.Element {
    const { preflight, moveMailConfirmed, addedDomainLoading, generatedDomain } = useValues(inboundEmailDomainsLogic)
    const { setMoveMailConfirmed, addDomain, setStep } = useActions(inboundEmailDomainsLogic)
    const domain = preflight?.domain ?? ''

    return (
        <div className="flex flex-col gap-3" data-attr="received-email-move-mail">
            <LemonBanner type="warning">
                {preflight?.existing_mx.length
                    ? `${domain} already gets mail through ${preflight.existing_mx.join(', ')}.`
                    : `${domain} is your whole domain, not a subdomain.`}{' '}
                Adding our record moves all of its mail to PostHog. Mailboxes on it stop getting mail, including
                people's work email.
            </LemonBanner>
            <div className="border rounded p-3 flex flex-col gap-2">
                <h4 className="m-0 text-sm font-semibold">Keep your mail where it is</h4>
                <p className="m-0 text-sm text-secondary">
                    Forward the mailboxes you want to your receiving address
                    {generatedDomain ? '' : ' or a new subdomain'}. Your addresses keep working and no DNS changes.
                </p>
                <div>
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={() => setStep('list')}
                        data-attr="received-email-use-forwarding"
                    >
                        Use forwarding instead
                    </LemonButton>
                </div>
            </div>
            <div className="border rounded p-3 flex flex-col gap-2">
                <h4 className="m-0 text-sm font-semibold">Move all mail for {domain} to PostHog</h4>
                <LemonCheckbox
                    checked={moveMailConfirmed}
                    onChange={setMoveMailConfirmed}
                    label={`I understand that all mail to ${domain} will stop reaching its current mailboxes`}
                    data-attr="received-email-confirm-move"
                />
                <div className="flex justify-between gap-2 flex-wrap">
                    <LemonButton onClick={() => setStep('form')}>Back</LemonButton>
                    <LemonButton
                        type="secondary"
                        status="danger"
                        loading={addedDomainLoading}
                        disabledReason={moveMailConfirmed ? undefined : 'Confirm that you understand first'}
                        onClick={() => addDomain()}
                        data-attr="received-email-move-mail-confirm"
                    >
                        Move mail to PostHog
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
