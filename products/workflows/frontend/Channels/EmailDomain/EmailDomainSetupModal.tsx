import { useEffect, useState } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { IntegrationType } from '~/types'

import { BindEmailDomainLogics } from './BindEmailDomainLogics'
import { AgentHandoffModal } from './components/AgentHandoffModal'
import { EmailDomainSetupEntry, captureEmailDomainSetupStarted, emailDomainSetupPath } from './emailDomainSetupLinks'
import { EmailDomainSteps } from './EmailDomainSteps'

const RETURNS_TO_EMAIL: EmailDomainSetupEntry[] = ['broadcast', 'email_step', 'transactional']

export interface EmailDomainSetupModalProps {
    integration?: IntegrationType | null
    entry: EmailDomainSetupEntry
    onComplete: (integrationId?: number) => void
    onClose: (savedIntegrationId?: number) => void
}

export function EmailDomainSetupModal({
    integration,
    entry,
    onComplete,
    onClose,
}: EmailDomainSetupModalProps): JSX.Element {
    const [integrationId, setIntegrationId] = useState<number | null>(integration?.id ?? null)

    useEffect(() => captureEmailDomainSetupStarted(entry), [entry])

    return (
        <LemonModal
            title={integrationId ? 'Verify your sending domain' : 'Set up a sending domain'}
            width={720}
            onClose={() => (integrationId ? onComplete(integrationId) : onClose())}
        >
            <BindEmailDomainLogics id={integrationId === null ? 'new' : String(integrationId)}>
                <div className="@container flex flex-col gap-6">
                    <EmailDomainSteps
                        domainLogicKey="modal"
                        onDomainCreated={(created) => setIntegrationId(created.id)}
                        existingOpensNewTab={RETURNS_TO_EMAIL.includes(entry)}
                        readyNextStep={
                            integrationId !== null && RETURNS_TO_EMAIL.includes(entry) ? (
                                <LemonButton
                                    type="primary"
                                    size="large"
                                    className="self-center"
                                    onClick={() => onComplete(integrationId)}
                                    data-attr="email-domain-use-sender"
                                >
                                    Use this sender
                                </LemonButton>
                            ) : undefined
                        }
                    />
                    {integrationId === null ? null : (
                        <LemonButton
                            type="tertiary"
                            className="self-center"
                            to={emailDomainSetupPath(integrationId)}
                            // An email saves its new sender a moment after the modal hands it over, so leaving the page
                            // right away would drop it. The full page opens next to the email instead.
                            targetBlank={RETURNS_TO_EMAIL.includes(entry)}
                            onClick={() => onComplete(integrationId)}
                            sideIcon={<IconExternal />}
                        >
                            Open full page
                        </LemonButton>
                    )}
                    <AgentHandoffModal />
                </div>
            </BindEmailDomainLogics>
        </LemonModal>
    )
}
