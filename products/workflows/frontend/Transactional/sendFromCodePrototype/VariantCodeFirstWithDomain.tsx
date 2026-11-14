// PROTOTYPE (ticket #320), variant BC, round 2: the code-first empty state of B, aware of the sending domain,
// paired with the first-send step on the domain setup page (PrototypeDomainReadyStep).
import { useState } from 'react'

import { IconCheckCircle, IconCode, IconCircleDashed } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonTag, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { urls } from 'scenes/urls'

import { PrototypeEmailsTable } from './PrototypeEmailsTable'
import { PrototypeFirstSendStatus } from './PrototypeFirstSendStatus'
import { PrototypeSendSnippet } from './PrototypeSendSnippet'
import { useSendFromCodePrototype } from './useSendFromCodePrototype'

export function VariantCodeFirstWithDomain(): JSX.Element {
    const { emails, domain, firstSend, withParams } = useSendFromCodePrototype()
    const [showSnippet, setShowSnippet] = useState(false)
    const [modalOpen, setModalOpen] = useState(false)
    const [bannerDismissed, setBannerDismissed] = useState(false)
    const verified = domain === 'verified'
    const from = verified ? 'Acme <hello@mail.example.com>' : undefined
    const domainPage = withParams('/workflows/channels/email/new')

    if (emails === 'some' || firstSend === 'arrived') {
        return (
            <div className="flex flex-col gap-2">
                {!bannerDismissed ? (
                    <LemonBanner
                        type="info"
                        onClose={() => setBannerDismissed(true)}
                        action={{ children: 'Show me how', onClick: () => setModalOpen(true) }}
                    >
                        Your code can send any email with one API call, no template needed. It shows up in this list
                        with its own metrics.
                    </LemonBanner>
                ) : null}
                <PrototypeEmailsTable />
                <LemonModal
                    isOpen={modalOpen}
                    onClose={() => setModalOpen(false)}
                    title="Send an email from your code"
                    width={720}
                >
                    <PrototypeSendSnippet from={from} />
                </LemonModal>
            </div>
        )
    }

    return (
        <div className="flex flex-col items-center py-8">
            <div className="flex flex-col gap-4 w-full max-w-180">
                <div className="flex flex-col gap-1 text-center items-center">
                    <IconCode className="text-3xl text-secondary" />
                    <h2 className="m-0 text-xl font-bold">Send your first email from code</h2>
                    <p className="m-0 text-secondary">
                        Password resets, receipts, sign-in codes: one API call from your server sends it, and PostHog
                        links it to the person who got it.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2 border rounded px-4 py-3 bg-surface-primary">
                    {verified ? (
                        <>
                            <IconCheckCircle className="text-success text-lg" />
                            <span className="flex-1 min-w-0">
                                Sending from <code>hello@mail.example.com</code>
                            </span>
                            <LemonTag type="success">Domain verified</LemonTag>
                        </>
                    ) : (
                        <>
                            <IconCircleDashed className="text-secondary text-lg" />
                            <span className="flex-1 min-w-0">
                                {domain === 'pending' ? (
                                    <>
                                        <code>mail.example.com</code> is waiting for its DNS records.
                                    </>
                                ) : (
                                    <>First, verify the domain you send from. Until then, test sends go to you.</>
                                )}
                            </span>
                            <LemonButton type="primary" size="small" to={domainPage}>
                                {domain === 'pending' ? 'Check DNS records' : 'Set up a domain'}
                            </LemonButton>
                        </>
                    )}
                </div>
                <div className="flex flex-col gap-2 border rounded p-4 bg-surface-primary">
                    <h3 className="m-0 text-base font-semibold">Let the Wizard write it</h3>
                    <p className="m-0 text-secondary text-sm">
                        Run this in your app's folder. The setup agent adds the API key and your first send. Moving from
                        SendGrid or Resend? Run <code>npx @posthog/wizard migrate-email</code> instead.
                    </p>
                    <CodeSnippet language={Language.Bash} compact wrap thing="Wizard command">
                        npx @posthog/wizard transactional-email
                    </CodeSnippet>
                </div>
                {showSnippet ? (
                    <div className="flex flex-col gap-2 border rounded p-4 bg-surface-primary">
                        <h3 className="m-0 text-base font-semibold">Write it yourself</h3>
                        <PrototypeSendSnippet from={from} />
                    </div>
                ) : (
                    <div className="flex justify-center">
                        <LemonButton type="secondary" onClick={() => setShowSnippet(true)}>
                            Write it yourself
                        </LemonButton>
                    </div>
                )}
                {verified ? <PrototypeFirstSendStatus /> : null}
                <p className="m-0 text-center text-secondary text-sm">
                    Want to design the email in PostHog instead?{' '}
                    <Link to={urls.transactionalNew()}>Create a template</Link>
                </p>
            </div>
        </div>
    )
}
