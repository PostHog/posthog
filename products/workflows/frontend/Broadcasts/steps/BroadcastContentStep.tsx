import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { EmailTemplater, TemplatePickerModal } from 'scenes/hog-functions/email-templater/EmailTemplater'
import type { EmailFieldErrors, EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import { IntegrationType } from '~/types'

import { EmailSetupModal } from '../../Channels/EmailSetup/EmailSetupModal'
import { buildSampleGlobals } from '../../Workflows/hogflows/steps/components/HogFlowFunctionConfiguration'
import { BroadcastEmailValue, DEFAULT_BROADCAST_EMAIL, broadcastWizardLogic } from '../broadcastWizardLogic'

export function BroadcastContentStep(): JSX.Element {
    const { email, stepValidationErrors, selectedSender } = useValues(broadcastWizardLogic)
    const { setEmail } = useActions(broadcastWizardLogic)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)
    const { loadIntegrations } = useActions(integrationsLogic)
    const [templatePickerOpen, setTemplatePickerOpen] = useState(false)
    // null: closed. 'new': set up a sender. An integration: finish verifying that one.
    const [senderSetup, setSenderSetup] = useState<'new' | IntegrationType | null>(null)

    const hasSenders = !!integrations?.some((integration) => integration.kind === 'email')
    const senderUnverified = !!selectedSender && selectedSender.config?.verified !== true

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
                    onClose={() => setSenderSetup(null)}
                    onComplete={(integrationId) => {
                        setSenderSetup(null)
                        loadIntegrations()
                        if (integrationId) {
                            setEmail({ ...email, from: { ...email.from, integrationId } })
                        }
                    }}
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
        </div>
    )
}
