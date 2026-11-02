import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { EmailSenderDetails } from 'scenes/hog-functions/email-templater/EmailSenderDetails'
import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import { EmailHtmlFrame } from './EmailHtmlFrame'

function ReadOnlySender({ email }: { email: EmailTemplate }): JSX.Element {
    const { integrations, integrationsLoading } = useValues(integrationsLogic)

    if (!integrations) {
        return integrationsLoading ? (
            <LemonSkeleton className="h-4 w-48" />
        ) : (
            <span className="text-secondary">Couldn't load the sender. Refresh the page to try again.</span>
        )
    }
    const senders = integrations.filter((integration) => integration.kind === 'email')
    return <EmailSenderDetails email={email} senders={senders} placeholder="No sender set" />
}

export function ReadOnlyTemplatePreview({ email }: { email: EmailTemplate }): JSX.Element {
    return (
        <div className="flex flex-col flex-1 gap-4 min-h-0" data-attr="message-template-read-only-preview">
            <div className="flex flex-col gap-3 rounded border bg-surface-primary p-3">
                <LemonField.Pure label="From" className="gap-1 min-w-0">
                    <ReadOnlySender email={email} />
                </LemonField.Pure>
                <LemonField.Pure label="Subject" className="gap-1 min-w-0">
                    <span className="break-words">{email.subject}</span>
                </LemonField.Pure>
                {email.preheader && (
                    <LemonField.Pure label="Preheader" className="gap-1 min-w-0">
                        <span className="break-words text-secondary">{email.preheader}</span>
                    </LemonField.Pure>
                )}
            </div>
            <LemonField.Pure label="HTML" className="gap-1 min-w-0">
                <EmailHtmlFrame html={email.html} className="h-128 rounded border" />
            </LemonField.Pure>
            <LemonField.Pure label="Plain text" className="gap-1 min-w-0">
                {email.text ? (
                    <pre className="m-0 rounded border bg-surface-primary p-3 text-sm whitespace-pre-wrap break-words">
                        {email.text}
                    </pre>
                ) : (
                    <span className="text-secondary">This template has no plain text version.</span>
                )}
            </LemonField.Pure>
        </div>
    )
}
