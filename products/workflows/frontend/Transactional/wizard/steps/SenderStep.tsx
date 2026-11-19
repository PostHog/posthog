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
    const { draft, senders } = useValues(transactionalEmailWizardLogic)
    const { updateEmail } = useActions(transactionalEmailWizardLogic)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)
    const { loadIntegrations } = useActions(integrationsLogic)
    const [senderSetupOpen, setSenderSetupOpen] = useState(false)
    const senderSetup = senderSetupOpen ? (
        <EmailSetupModal
            entry="transactional"
            onComplete={() => setSenderSetupOpen(false)}
            onClose={() => setSenderSetupOpen(false)}
        />
    ) : null

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
                            onClick={() => setSenderSetupOpen(true)}
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
                        {senderSetup}
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
                    onAddSender={() => setSenderSetupOpen(true)}
                />
            </LemonField.Pure>
            {senderSetup}
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
