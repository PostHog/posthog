import { useActions, useValues } from 'kea'

import { IconGlobe, IconLetter, IconSend } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Spinner } from '@posthog/lemon-ui'

import { inboundEmailDomainsLogic } from './inboundEmailDomainsLogic'
import { ReceivingAddress } from './ReceivingAddress'

function SetupCard({
    icon,
    title,
    children,
}: {
    icon: JSX.Element
    title: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <section className="border rounded bg-surface-primary p-4 flex flex-col gap-2 min-w-0">
            <h3 className="m-0 text-sm font-semibold flex items-center gap-2">
                <span className="text-secondary text-lg flex">{icon}</span>
                {title}
            </h3>
            {children}
        </section>
    )
}

/** What a project sees until its first email arrives. The ready-made address comes first because it needs no setup. */
export function ReceivingSetup(): JSX.Element {
    const { overview, generatedDomain, overviewLoading, addressLoading, customDomains } =
        useValues(inboundEmailDomainsLogic)
    const { startAddingDomain, openDomains } = useActions(inboundEmailDomainsLogic)
    const receivingDomain = generatedDomain?.domain ?? customDomains.find((d) => d.status === 'active')?.domain
    const offersAddress = overview?.generated_addresses_available

    return (
        <div className="flex flex-col gap-3" data-attr="received-email-setup">
            {offersAddress !== false && (
                <SetupCard icon={<IconLetter />} title="Your receiving address">
                    {generatedDomain ? (
                        <>
                            <ReceivingAddress domain={generatedDomain.domain} />
                            <p className="m-0 text-sm text-secondary">
                                Send to any name at this address. It works now, with no DNS setup.
                            </p>
                        </>
                    ) : overviewLoading || addressLoading ? (
                        <LemonSkeleton className="h-5 w-80" />
                    ) : (
                        <p className="m-0 text-sm text-secondary">
                            This address couldn't load. Reload the page to retry.
                        </p>
                    )}
                </SetupCard>
            )}
            {receivingDomain && (
                <div
                    className="flex items-center gap-2 text-sm text-secondary px-1"
                    data-attr="received-email-waiting"
                    aria-live="polite"
                >
                    <Spinner className="text-base" />
                    Waiting for your first email. It shows up here within a few seconds.
                </div>
            )}
            <div className="grid gap-3 @container grid-cols-[repeat(auto-fit,minmax(18rem,1fr))]">
                <SetupCard icon={<IconSend />} title="Keep your current address">
                    <p className="m-0 text-sm text-secondary">
                        Forward a mailbox such as support@yourcompany.com to the address above. That address keeps
                        working and your mail stays where it is. Gmail and Outlook ask you to confirm with a code, which
                        shows up here under Filtered.
                    </p>
                </SetupCard>
                <SetupCard icon={<IconGlobe />} title="Use your own domain">
                    <p className="m-0 text-sm text-secondary">
                        Receive at an address such as hello@inbound.yourcompany.com by adding one MX record to a
                        subdomain.
                    </p>
                    <div className="flex gap-2 mt-1">
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => startAddingDomain()}
                            data-attr="received-email-add-domain"
                        >
                            Add domain
                        </LemonButton>
                        {customDomains.length > 0 && (
                            <LemonButton size="small" onClick={() => openDomains()}>
                                View your {customDomains.length === 1 ? 'domain' : 'domains'}
                            </LemonButton>
                        )}
                    </div>
                </SetupCard>
            </div>
        </div>
    )
}
