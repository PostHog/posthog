import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { EmailTemplater, TemplatePickerModal } from 'scenes/hog-functions/email-templater/EmailTemplater'
import type { EmailFieldErrors, EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import { IntegrationType } from '~/types'

import { EmailSetupModal } from '../../Channels/EmailSetup/EmailSetupModal'
import { buildSampleGlobals } from '../../Workflows/hogflows/steps/components/HogFlowFunctionConfiguration'
import { UtmTagFields } from '../../Workflows/hogflows/steps/components/UtmTagFields'
import { BroadcastEmailValue, DEFAULT_BROADCAST_EMAIL, broadcastWizardLogic } from '../broadcastWizardLogic'

export function BroadcastContentStep(): JSX.Element {
    const { broadcast, email, name, stepValidationErrors, selectedSender, emailSettings } =
        useValues(broadcastWizardLogic)
    const { setEmail, setEmailSettings } = useActions(broadcastWizardLogic)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)
    const { loadIntegrations } = useActions(integrationsLogic)
    const [templatePickerOpen, setTemplatePickerOpen] = useState(false)
    // null: closed. 'new': set up a sender. An integration: finish verifying that one.
    const [senderSetup, setSenderSetup] = useState<'new' | IntegrationType | null>(null)

    const hasSenders = !!integrations?.some((integration) => integration.kind === 'email')
    const senderUnverified = !!selectedSender && selectedSender.config?.verified !== true

    // Closing the modal after Continue also keeps the sender it created or verified.
    const closeSenderSetup = (integrationId?: number): void => {
        setSenderSetup(null)
        if (integrationId) {
            loadIntegrations()
            setEmail({ ...email, from: { ...email.from, integrationId } })
        }
    }

    const errors = stepValidationErrors.content
    const fieldErrors: EmailFieldErrors = {
        from: errors.find((error) => error.includes('sender')),
        subject: errors.find((error) => error.includes('subject')),
        body: errors.find((error) => error.includes('content')),
    }

    return (
        <div className="flex flex-col gap-2 min-h-[36rem]">
            <div className="flex items-start justify-between gap-2">
                <div>
                    <h2 className="m-0 text-xl font-semibold">Write your email</h2>
                    <p className="m-0 text-secondary">Pick a sender, add a subject, and design the email.</p>
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => setTemplatePickerOpen(true)}
                    data-attr="broadcast-wizard-template-picker"
                >
                    Start from template
                </LemonButton>
            </div>
            <TemplatePickerModal isOpen={templatePickerOpen} onClose={() => setTemplatePickerOpen(false)} />
            {!integrationsLoading && integrations && !hasSenders ? (
                <LemonBanner
                    type="info"
                    action={{
                        children: 'Set up email sender',
                        onClick: () => setSenderSetup('new'),
                        'data-attr': 'broadcast-setup-sender',
                    }}
                >
                    Broadcasts send from your own domain. Set up a sender, then verify the domain with a few DNS
                    records.
                </LemonBanner>
            ) : senderUnverified ? (
                <LemonBanner
                    type="warning"
                    action={{
                        children: 'Verify domain',
                        onClick: () => setSenderSetup(selectedSender),
                        'data-attr': 'broadcast-verify-sender',
                    }}
                >
                    {selectedSender?.display_name} is not verified yet. You can keep writing, but the broadcast can't
                    send until its domain is verified.
                </LemonBanner>
            ) : null}
            {senderSetup ? (
                <EmailSetupModal
                    integration={senderSetup === 'new' ? undefined : senderSetup}
                    onClose={closeSenderSetup}
                    onComplete={closeSenderSetup}
                />
            ) : null}
            <EmailTemplater
                type="native_email"
                templating="liquid"
                liveChanges
                value={email as unknown as EmailTemplate}
                defaultValue={DEFAULT_BROADCAST_EMAIL as unknown as EmailTemplate}
                onChange={(value) => setEmail(value as unknown as BroadcastEmailValue)}
                variables={buildSampleGlobals({ type: 'batch' }, null)}
                fieldErrors={fieldErrors}
            />
            {email.to?.email && !email.to.email.includes('{{') ? (
                <span className="text-xs text-warning" data-attr="broadcast-fixed-recipient-hint">
                    Every email in this broadcast goes to {email.to.email}, not to each person in the audience. Use{' '}
                    <code>{'{{ person.properties.email }}'}</code> to send each person their own email.
                </span>
            ) : null}
            <LemonSwitch
                label="Track opens and link clicks"
                checked={emailSettings.trackingEnabled}
                onChange={(trackingEnabled) => setEmailSettings({ trackingEnabled })}
                bordered
                data-attr="broadcast-tracking-toggle"
            />
            {!emailSettings.trackingEnabled && (
                <span className="text-xs text-secondary">
                    Links stay as written and no tracking pixel is added, so this broadcast shows no opens or clicks.
                </span>
            )}
            <LemonSwitch
                label="Add UTM tags to links"
                checked={emailSettings.utmTagsEnabled}
                onChange={(utmTagsEnabled) => setEmailSettings({ utmTagsEnabled })}
                bordered
                data-attr="broadcast-utm-tags-toggle"
            />
            {emailSettings.utmTagsEnabled && (
                <UtmTagFields
                    value={emailSettings.utmParams}
                    onChange={(utmParams) => setEmailSettings({ utmParams })}
                    campaignDefault={name || 'Broadcast name'}
                    contentDefault={
                        broadcast?.actions?.find((action) => action.type === 'function_email')?.name ?? 'Send email'
                    }
                />
            )}
        </div>
    )
}
