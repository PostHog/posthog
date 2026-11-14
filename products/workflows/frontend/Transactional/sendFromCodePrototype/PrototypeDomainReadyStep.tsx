// PROTOTYPE (ticket #320), variant BC, round 2: the domain setup page's "ready" step offers the first send
// from code before the workflow choices. Invented domain; the real step reads it from the domain's logics.
import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { urls } from 'scenes/urls'

import { StepHeading } from '../../Channels/EmailDomain/components/StepHeading'
import { HedgehogMailbox, HedgehogRocket } from '../../Channels/EmailDomain/hoggies'
import { PrototypeFirstSendStatus } from './PrototypeFirstSendStatus'
import { PrototypeSendSnippet } from './PrototypeSendSnippet'
import { useSendFromCodePrototype } from './useSendFromCodePrototype'

export function PrototypeDomainReadyStep(): JSX.Element {
    const { firstSend, set, withParams } = useSendFromCodePrototype()

    return (
        <div className="flex flex-col gap-8">
            <div className="rounded-xl border border-success bg-success-highlight p-6 @md:p-8">
                <StepHeading
                    Hoggie={HedgehogRocket}
                    title="You can send from mail.example.com"
                    lead="All 4 settings are in place. Inboxes now know these emails really come from you."
                />
            </div>
            <section className="rounded-xl border border-accent bg-accent-highlight-secondary p-6 @md:p-8 flex flex-col gap-5">
                <div className="flex items-start gap-4">
                    <HedgehogMailbox className="w-20 shrink-0" />
                    <div className="flex flex-col gap-1 min-w-0">
                        <span className="text-xs uppercase tracking-wide text-secondary">Next</span>
                        <h2 className="m-0 text-xl font-semibold">Send your first email from your code</h2>
                        <p className="m-0 text-sm text-secondary">
                            One API call from your server sends a sign-in code, a receipt or a password reset from{' '}
                            <span className="font-mono">hello@mail.example.com</span>. PostHog links every email to the
                            person who got it.
                        </p>
                    </div>
                </div>
                {firstSend === 'arrived' ? (
                    <div className="flex flex-col gap-3">
                        <PrototypeFirstSendStatus />
                        <LemonButton
                            type="primary"
                            className="self-start"
                            to={withParams(urls.transactional(), { emails: 'some' })}
                        >
                            See it in Transactional emails
                        </LemonButton>
                    </div>
                ) : (
                    <>
                        <div className="flex flex-col gap-2">
                            <h3 className="m-0 text-base font-semibold">Let the Wizard write it</h3>
                            <p className="m-0 text-sm text-secondary">
                                Run this in your app's folder. The setup agent adds the API key to your env file and
                                writes the first send with this sender.
                            </p>
                            <CodeSnippet language={Language.Bash} compact wrap thing="Wizard command">
                                npx @posthog/wizard transactional-email
                            </CodeSnippet>
                            <p className="m-0 text-xs text-secondary">
                                Moving from SendGrid or Resend? Run <code>npx @posthog/wizard migrate-email</code>{' '}
                                instead.
                            </p>
                        </div>
                        <div className="flex flex-col gap-2">
                            <h3 className="m-0 text-base font-semibold">Or write it yourself</h3>
                            <PrototypeSendSnippet from="Acme <hello@mail.example.com>" compact />
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                            <LemonButton type="secondary" size="small" onClick={() => set({ firstSend: 'arrived' })}>
                                Send a test to my inbox
                            </LemonButton>
                            <span className="text-xs text-secondary">
                                From <code>hello@mail.example.com</code>, to the address you sign in with.
                            </span>
                        </div>
                        <PrototypeFirstSendStatus />
                    </>
                )}
            </section>
            <section className="rounded-xl border p-5 flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2 min-w-0">
                    <IconCheckCircle className="text-secondary text-lg shrink-0" />
                    <span className="text-sm">
                        <b>Prefer an automation?</b> Start a workflow that sends from this domain, like a welcome
                        series.
                    </span>
                </div>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                    <Link to={urls.workflows('library')}>Pick a template</Link>
                    <Link to={urls.workflows()}>Go to workflows</Link>
                </div>
            </section>
        </div>
    )
}
