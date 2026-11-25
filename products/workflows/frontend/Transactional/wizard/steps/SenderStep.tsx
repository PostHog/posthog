import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { senderFrom } from 'scenes/hog-functions/email-templater/emailSenderFields'
import { EmailSenderForm } from 'scenes/hog-functions/email-templater/EmailSenderForm'
import { EmailSenderPicker } from 'scenes/hog-functions/email-templater/EmailSenderPicker'

import { EmailSetupModal } from '../../../Channels/EmailSetup/EmailSetupModal'
import { transactionalEmailWizardLogic } from '../transactionalEmailWizardLogic'

export function SenderStep(): JSX.Element {
    const { draft } = useValues(transactionalEmailWizardLogic)
    const { updateEmail } = useActions(transactionalEmailWizardLogic)
    const { loadIntegrations } = useActions(integrationsLogic)
    const [senderSetupOpen, setSenderSetupOpen] = useState(false)
    const from = senderFrom(draft.email)

    const finishSenderSetup = (integrationId?: number): void => {
        setSenderSetupOpen(false)
        loadIntegrations()
        if (integrationId && !from.integrationId) {
            updateEmail({ from: { ...from, integrationId } })
        }
    }

    // A new sender swaps the empty state for the picker, so the setup sits outside both to stay open.
    return (
        <>
            <SenderStepContent onAddSender={() => setSenderSetupOpen(true)} />
            {senderSetupOpen ? (
                <EmailSetupModal entry="transactional" onComplete={finishSenderSetup} onClose={finishSenderSetup} />
            ) : null}
        </>
    )
}

function SenderStepContent({ onAddSender }: { onAddSender: () => void }): JSX.Element {
    const { draft, senders } = useValues(transactionalEmailWizardLogic)
    const { updateEmail } = useActions(transactionalEmailWizardLogic)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)
    const { loadIntegrations } = useActions(integrationsLogic)

    // A failed load clears the loading flag, and falls through to the retry below.
    if (integrations === null && integrationsLoading) {
        return <Spinner className="text-lg" />
    }

    if (senders.length === 0) {
        return (
            <ProductIntroduction
                titleOverride="Set up a sending domain first"
                thingName="email sender"
                description="Transactional emails send from a verified domain. Set one up here. Once it's verified, you can finish this email."
                isEmpty
                actionElementOverride={
                    <div className="flex gap-2 flex-wrap">
                        <LemonButton
                            type="primary"
                            onClick={onAddSender}
                            data-attr="transactional-email-wizard-setup-sender"
                        >
                            Set up a sending domain
                        </LemonButton>
                        {/* Verification can finish after the setup closes, so this picks up the sender then. */}
                        <LemonButton
                            type="secondary"
                            onClick={loadIntegrations}
                            loading={integrationsLoading}
                            data-attr="transactional-email-wizard-check-senders"
                        >
                            Check again
                        </LemonButton>
                    </div>
                }
            />
        )
    }

    const from = senderFrom(draft.email)

    return (
        <div className="max-w-160 flex flex-col gap-3 [&>div]:w-full [&>div]:p-0">
            <LemonField.Pure label="Sender">
                <EmailSenderPicker
                    from={from}
                    senders={senders}
                    dataAttrPrefix="transactional-email"
                    onChangeFrom={(next) => updateEmail({ from: next })}
                    onAddSender={onAddSender}
                />
            </LemonField.Pure>
            <EmailSenderForm
                from={from}
                replyTo={draft.email.replyTo}
                senders={senders}
                dataAttrPrefix="transactional-email"
                onChangeFrom={(next) => updateEmail({ from: next })}
                onChangeReplyTo={(replyTo) => updateEmail({ replyTo })}
                onClear={() => updateEmail({ from: { ...from, name: undefined, email: undefined }, replyTo: '' })}
            />
        </div>
    )
}
