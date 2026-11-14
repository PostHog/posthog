// PROTOTYPE (ticket #320), variant A: a "Send from code" page, the first tab of the Transactional section.
import { IconCheckCircle, IconCircleDashed } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { PrototypeAgentSetup } from './PrototypeAgentSetup'
import { PrototypeFirstSendStatus } from './PrototypeFirstSendStatus'
import { PrototypeSendSnippet } from './PrototypeSendSnippet'
import { useSendFromCodePrototype } from './useSendFromCodePrototype'

function Step({
    number,
    title,
    done,
    children,
}: {
    number: number
    title: string
    done?: boolean
    children: React.ReactNode
}): JSX.Element {
    return (
        <li className="flex gap-3 min-w-0">
            <span className="mt-0.5 shrink-0 text-lg">
                {done ? <IconCheckCircle className="text-success" /> : <IconCircleDashed className="text-secondary" />}
            </span>
            <div className="flex flex-col gap-2 min-w-0 flex-1">
                <h3 className="m-0 text-base font-semibold">
                    {number}. {title}
                </h3>
                {children}
            </div>
        </li>
    )
}

export function VariantSendFromCodePage(): JSX.Element {
    const { domain } = useSendFromCodePrototype()

    return (
        <div className="@container flex flex-col gap-4 max-w-300">
            <div className="flex flex-col gap-1">
                <h2 className="m-0 text-xl font-bold">Send email from your code</h2>
                <p className="m-0 text-secondary max-w-180">
                    One API call sends a password reset, a receipt or a sign-in code. You write the email in your code,
                    and every send is linked to the person who got it, so it shows on their profile next to their
                    events.
                </p>
            </div>
            <div className="grid grid-cols-1 @min-[60rem]:grid-cols-[minmax(0,1fr)_20rem] gap-6">
                <ol className="m-0 p-0 list-none flex flex-col gap-5">
                    <Step number={1} title="Verify the domain you send from" done={domain === 'verified'}>
                        {domain === 'verified' ? (
                            <div className="flex flex-wrap items-center gap-2">
                                <code>mail.example.com</code>
                                <LemonTag type="success">Verified</LemonTag>
                                <LemonButton size="xsmall" type="tertiary" to={urls.transactional('channels')}>
                                    Manage
                                </LemonButton>
                            </div>
                        ) : (
                            <div className="flex flex-wrap items-center gap-2">
                                {domain === 'pending' ? (
                                    <>
                                        <code>mail.example.com</code>
                                        <LemonTag type="warning">Waiting for DNS</LemonTag>
                                    </>
                                ) : null}
                                <LemonButton size="small" type="secondary" to={urls.transactional('channels')}>
                                    {domain === 'pending' ? 'Check DNS records' : 'Add a domain'}
                                </LemonButton>
                                <span className="text-xs text-secondary">
                                    Until then, you can send test emails to your own address.
                                </span>
                            </div>
                        )}
                    </Step>
                    <Step number={2} title="Create a secret API key">
                        <div className="flex flex-wrap items-center gap-2">
                            <LemonButton
                                size="small"
                                type="secondary"
                                to={urls.settings('environment-secret-api-keys')}
                            >
                                Create key
                            </LemonButton>
                            <span className="text-xs text-secondary">
                                With the <code>transactional_email:write</code> scope. Keep it on your server.
                            </span>
                        </div>
                    </Step>
                    <Step number={3} title="Send your first email">
                        <PrototypeSendSnippet
                            from={domain === 'verified' ? 'Acme <hello@mail.example.com>' : undefined}
                        />
                        <PrototypeFirstSendStatus />
                    </Step>
                </ol>
                <aside className="flex flex-col gap-3 border rounded p-4 bg-surface-primary h-fit">
                    <PrototypeAgentSetup />
                </aside>
            </div>
        </div>
    )
}
