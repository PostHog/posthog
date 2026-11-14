// PROTOTYPE (ticket #320), variant B: the Transactional emails list leads with code when it is empty,
// and keeps a one-line reminder above the list once emails exist.
import { useState } from 'react'

import { IconCode } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { urls } from 'scenes/urls'

import { PrototypeEmailsTable } from './PrototypeEmailsTable'
import { PrototypeSendSnippet } from './PrototypeSendSnippet'
import { useSendFromCodePrototype } from './useSendFromCodePrototype'

export function VariantCodeFirstEmptyState(): JSX.Element {
    const { emails, domain } = useSendFromCodePrototype()
    const [showSnippet, setShowSnippet] = useState(false)
    const [modalOpen, setModalOpen] = useState(false)
    const [bannerDismissed, setBannerDismissed] = useState(false)
    const from = domain === 'verified' ? 'Acme <hello@mail.example.com>' : undefined

    if (emails === 'some') {
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
                <div className="flex flex-col gap-2 border rounded p-4 bg-surface-primary">
                    <h3 className="m-0 text-base font-semibold">Let the Wizard write it</h3>
                    <p className="m-0 text-secondary text-sm">
                        Run this in your app's folder. The setup agent adds the API key and your first send. Moving from
                        SendGrid or Resend? Run <code>npx @posthog/wizard migrate-email</code> instead.
                    </p>
                    <CodeSnippet language={Language.Bash} compact thing="Wizard command">
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
                <p className="m-0 text-center text-secondary text-sm">
                    Want to design the email in PostHog instead?{' '}
                    <Link to={urls.transactionalNew()}>Create a template</Link>
                </p>
            </div>
        </div>
    )
}
