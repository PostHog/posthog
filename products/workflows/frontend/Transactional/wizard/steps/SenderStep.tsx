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
                description="Transactional emails send from a verified domain. Verify one in a new tab, then check again here to finish this email."
                isEmpty
                actionElementOverride={
                    <div className="flex gap-2 flex-wrap">
                        <LemonButton type="primary" to={urls.transactional('channels')} targetBlank>
                            Set up a sending domain
                        </LemonButton>
                        {/* Domain setup opens in a new tab, so this picks up the sender without losing the email. */}
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
