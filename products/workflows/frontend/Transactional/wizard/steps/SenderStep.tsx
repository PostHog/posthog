import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { senderFrom } from 'scenes/hog-functions/email-templater/emailSenderFields'
import { EmailSenderForm } from 'scenes/hog-functions/email-templater/EmailSenderForm'
import { urls } from 'scenes/urls'

import { transactionalEmailWizardLogic } from '../transactionalEmailWizardLogic'

export function SenderStep(): JSX.Element {
    const { draft, senders } = useValues(transactionalEmailWizardLogic)
    const { updateEmail } = useActions(transactionalEmailWizardLogic)
    const { integrationsLoading } = useValues(integrationsLogic)

    if (integrationsLoading && senders.length === 0) {
        return <Spinner className="text-lg" />
    }

    if (senders.length === 0) {
        return (
            <ProductIntroduction
                titleOverride="Set up a sending domain first"
                thingName="email sender"
                description="Transactional emails send from your own domain. Verify a sending domain first, then come back to finish this email."
                isEmpty
                actionElementOverride={
                    <LemonButton type="primary" to={urls.transactional('channels')} targetBlank>
                        Set up a sending domain
                    </LemonButton>
                }
            />
        )
    }

    return (
        <div className="max-w-160 [&>div]:w-full [&>div]:p-0">
            <EmailSenderForm
                from={senderFrom(draft.email)}
                replyTo={draft.email.replyTo}
                senders={senders}
                onChangeFrom={(from) => updateEmail({ from })}
                onChangeReplyTo={(replyTo) => updateEmail({ replyTo })}
            />
        </div>
    )
}
