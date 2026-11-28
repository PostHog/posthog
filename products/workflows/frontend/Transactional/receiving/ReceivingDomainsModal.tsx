import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonModal } from '@posthog/lemon-ui'

import { AddReceivingDomainForm, ConfirmMoveMail } from './AddReceivingDomainForm'
import { inboundEmailDomainsLogic } from './inboundEmailDomainsLogic'
import { ReceivingAddress } from './ReceivingAddress'
import { ReceivingDomainRow } from './ReceivingDomainRow'

const TITLES = { list: 'Receiving addresses', form: 'Add your own domain', confirm: 'This moves your mail' }

export function ReceivingDomainsModal(): JSX.Element {
    const { step, generatedDomain, customDomains, overview } = useValues(inboundEmailDomainsLogic)
    const { setStep, startAddingDomain, rotateAddress } = useActions(inboundEmailDomainsLogic)

    return (
        <LemonModal
            isOpen={step !== 'closed'}
            onClose={() => setStep('closed')}
            title={step === 'closed' ? '' : TITLES[step]}
            width={600}
        >
            {step === 'form' && <AddReceivingDomainForm />}
            {step === 'confirm' && <ConfirmMoveMail />}
            {step === 'list' && (
                <div className="flex flex-col gap-4">
                    {generatedDomain && (
                        <section className="flex flex-col gap-2">
                            <h4 className="m-0 text-sm font-semibold">Ready-made address</h4>
                            <div className="border rounded p-3 flex flex-wrap items-center justify-between gap-2">
                                <ReceivingAddress domain={generatedDomain.domain} />
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    data-attr="received-email-rotate-address"
                                    onClick={() =>
                                        LemonDialog.open({
                                            title: 'Change this address?',
                                            description:
                                                "You'll get a new address, and mail to the old one will be dropped. Update anything that forwards or sends to it. Email you've already received stays.",
                                            primaryButton: {
                                                children: 'Change address',
                                                status: 'danger',
                                                onClick: () => rotateAddress(),
                                            },
                                            secondaryButton: { children: 'Cancel' },
                                        })
                                    }
                                >
                                    Change address
                                </LemonButton>
                            </div>
                            <p className="m-0 text-sm text-secondary">
                                To keep an existing address such as support@yourcompany.com, forward its mail here. It
                                keeps working as it does today.
                            </p>
                        </section>
                    )}
                    <section className="flex flex-col gap-2">
                        <div className="flex items-center justify-between gap-2">
                            <h4 className="m-0 text-sm font-semibold">Your own domains</h4>
                            <LemonButton
                                size="small"
                                type="secondary"
                                onClick={() => startAddingDomain()}
                                data-attr="received-email-add-domain"
                            >
                                Add domain
                            </LemonButton>
                        </div>
                        {customDomains.length === 0 ? (
                            <p className="m-0 text-sm text-secondary">
                                None yet. A subdomain needs one MX record and doesn't affect your other mail.
                            </p>
                        ) : (
                            customDomains.map((domain) => <ReceivingDomainRow key={domain.id} domain={domain} />)
                        )}
                    </section>
                    {overview && (
                        <p className="m-0 text-xs text-secondary">
                            Received email is kept for {overview.retention_days} days. Spam and auto-replies are kept
                            under Filtered and fire no events.
                        </p>
                    )}
                </div>
            )}
        </LemonModal>
    )
}
