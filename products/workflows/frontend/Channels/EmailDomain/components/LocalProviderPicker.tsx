import { useActions, useValues } from 'kea'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { EmailDomainWizardLogicProps, EmailSenderProvider, emailDomainWizardLogic } from '../emailDomainWizardLogic'

const PROVIDER_NOTES: Record<EmailSenderProvider, string> = {
    maildev: 'Verifies right away. Emails go to the local inbox at localhost:1080.',
    ses: 'Uses the SES account from your local settings. The domain needs real DNS records to verify.',
}

export function LocalProviderPicker(props: EmailDomainWizardLogicProps): JSX.Element | null {
    const logic = emailDomainWizardLogic(props)
    const { isLocalStack, localProvider } = useValues(logic)
    const { setLocalProvider } = useActions(logic)
    if (!isLocalStack) {
        return null
    }
    return (
        <div className="flex flex-col gap-2 rounded border border-dashed p-3">
            <span className="text-sm">Send through (local stack only)</span>
            <LemonSegmentedButton
                size="small"
                value={localProvider}
                onChange={setLocalProvider}
                options={[
                    { value: 'maildev', label: 'Maildev', 'data-attr': 'email-domain-local-provider-maildev' },
                    { value: 'ses', label: 'Amazon SES', 'data-attr': 'email-domain-local-provider-ses' },
                ]}
            />
            <span className="text-xs text-secondary">{PROVIDER_NOTES[localProvider]}</span>
        </div>
    )
}
