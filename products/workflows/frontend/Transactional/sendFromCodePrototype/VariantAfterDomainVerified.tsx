// PROTOTYPE (ticket #320), variant C: the moment a sending domain verifies, the app offers the first send
// from code. In the real app the check runs in the domain setup modal; here a card stands in for it.
import { IconCheckCircle, IconCircleDashed } from '@posthog/icons'
import { LemonButton, LemonModal, LemonTag } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'

import { PrototypeAgentSetup } from './PrototypeAgentSetup'
import { PrototypeEmailsTable } from './PrototypeEmailsTable'
import { PrototypeFirstSendStatus } from './PrototypeFirstSendStatus'
import { PrototypeSendSnippet } from './PrototypeSendSnippet'
import { useSendFromCodePrototype } from './useSendFromCodePrototype'

const FROM = 'Acme <hello@mail.example.com>'

export function VariantAfterDomainVerified(): JSX.Element {
    const { domain, emails, firstSend, view, set } = useSendFromCodePrototype()
    const modalOpen = view === 'verified'

    return (
        <div className="flex flex-col gap-3">
            {firstSend !== 'arrived' ? (
                <LemonCard hoverEffect={false} className="p-4">
                    <div className="flex flex-col gap-3">
                        <h3 className="m-0 text-base font-semibold">Start sending email</h3>
                        <ol className="m-0 p-0 list-none flex flex-col gap-2">
                            <li className="flex flex-wrap items-center gap-2">
                                {domain === 'verified' ? (
                                    <IconCheckCircle className="text-success text-lg" />
                                ) : (
                                    <IconCircleDashed className="text-secondary text-lg" />
                                )}
                                <span>
                                    Verify <code>mail.example.com</code>
                                </span>
                                {domain === 'pending' ? <LemonTag type="warning">Waiting for DNS</LemonTag> : null}
                                {domain !== 'verified' ? (
                                    <LemonButton
                                        size="small"
                                        type="primary"
                                        onClick={() => set({ domain: 'verified', view: 'verified' })}
                                    >
                                        {domain === 'pending' ? 'Check DNS records' : 'Add a domain'}
                                    </LemonButton>
                                ) : null}
                            </li>
                            <li className="flex flex-wrap items-center gap-2">
                                <IconCircleDashed className="text-secondary text-lg" />
                                <span>Send your first email from code</span>
                                {domain === 'verified' ? (
                                    <LemonButton size="small" type="primary" onClick={() => set({ view: 'verified' })}>
                                        Show me how
                                    </LemonButton>
                                ) : (
                                    <span className="text-xs text-secondary">Opens once the domain verifies</span>
                                )}
                            </li>
                        </ol>
                    </div>
                </LemonCard>
            ) : null}
            {emails === 'some' || firstSend === 'arrived' ? (
                <PrototypeEmailsTable />
            ) : (
                <div className="text-secondary text-center py-8 border rounded border-dashed">
                    Emails your code sends show up here.
                </div>
            )}
            <LemonModal
                isOpen={modalOpen}
                onClose={() => set({ view: null })}
                title={
                    <span className="flex items-center gap-2">
                        <IconCheckCircle className="text-success" />
                        mail.example.com is verified
                    </span>
                }
                description="You can send from any address at this domain. Send your first email now, from your code."
                width={960}
                footer={
                    <LemonButton type="secondary" onClick={() => set({ view: null })}>
                        I'll do this later
                    </LemonButton>
                }
            >
                <div className="@container">
                    <div className="grid grid-cols-1 @min-[48rem]:grid-cols-[minmax(0,1fr)_18rem] gap-4">
                        <div className="flex flex-col gap-3 min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    onClick={() => set({ firstSend: 'arrived' })}
                                >
                                    Send a test to my inbox
                                </LemonButton>
                                <span className="text-xs text-secondary">
                                    From <code>hello@mail.example.com</code>, to the address you sign in with.
                                </span>
                            </div>
                            <PrototypeSendSnippet from={FROM} compact />
                            <PrototypeFirstSendStatus />
                        </div>
                        <div className="@min-[48rem]:border-l @min-[48rem]:pl-4">
                            <PrototypeAgentSetup />
                        </div>
                    </div>
                </div>
            </LemonModal>
        </div>
    )
}
